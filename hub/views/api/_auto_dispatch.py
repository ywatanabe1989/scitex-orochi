"""``/api/auto-dispatch/{fire,status}/`` — operator-facing triggers + inspection.

Companion to ``hub.auto_dispatch.check_agent_auto_dispatch`` (PR #334),
which runs from the heartbeat hot path. These endpoints expose the
auto-dispatch state orochi_machine to the CLI (``scitex-orochi dispatch
{run,status}``, Phase 1c msg#16477):

* ``POST /api/auto-dispatch/fire/`` — force an immediate dispatch DM to
  the named ``head-<host>`` agent, bypassing the streak / cooldown gate.
  Optional ``todo`` number in the body overrides the pick-helper result.
  Token-authenticated (workspace token), same auth pattern as
  ``api_agents_purge``.

* ``GET /api/auto-dispatch/status/`` — surface per-head ``idle_streak``,
  ``auto_dispatch_last_fire_ts`` (ISO), and derived ``cooldown_active``
  from the in-memory ``hub.registry`` dict. Read-only. Complements the
  orochi_machine-card resource view so operators can see "why isn't head-X
  being dispatched?" without tailing logs.

Auth: workspace token (same pattern as ``api_agents``) — the CLI already
has the token in env, and we don't want to require a browser session for
a fleet-coordination verb.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from hub.views.api._common import (
    JsonResponse,
    csrf_exempt,
    json,
    require_GET,
    require_http_methods,
)

log = logging.getLogger("orochi.auto_dispatch.api")


# ---------------------------------------------------------------------------
# Token auth helper (inlined for module self-containment)
# ---------------------------------------------------------------------------

def _resolve_workspace_from_token(request, body: dict | None = None):
    """Validate a workspace token and return (workspace, error_json_response).

    Accepts token from ?token= querystring OR JSON body.token (for POST).
    On success returns ``(workspace, None)``; on failure ``(None, JsonResponse)``.

    Unlike the subdomain-aware ``get_workspace``, this resolves the
    workspace from the token itself so the endpoint works on the bare
    domain, on workspace subdomains, and in test contexts with
    ``testserver`` HTTP_HOST.
    """
    token = request.GET.get("token")
    if not token and body and isinstance(body, dict):
        token = body.get("token")
    if not token:
        return None, JsonResponse({"error": "token required"}, status=401)
    from hub.models import WorkspaceToken

    try:
        row = WorkspaceToken.objects.get(token=token)
    except WorkspaceToken.DoesNotExist:
        return None, JsonResponse({"error": "invalid token"}, status=401)
    return row.workspace, None


# ---------------------------------------------------------------------------
# POST /api/auto-dispatch/fire/
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST"])
def api_auto_dispatch_fire(request):
    """Force an auto-dispatch DM to a ``head-<host>`` agent now.

    Bypasses the streak/cooldown gate that the heartbeat path uses.
    Useful for operators who want to nudge an idle head without waiting
    for the next two heartbeats to accumulate a streak, or for testing.

    Request body (JSON)::

        {
          "token":    "wks_...",     # workspace token (or ?token=)
          "head":     "<hostname>",  # e.g. "mba" → head-mba
          "todo":     123,           # optional; override pick-helper result
          "reason":   "operator-manual"   # optional audit tag
        }

    Returns::

        {"status":"ok","decision":"fired","message_id":N,"pick":{...}|null}

    or a structured error envelope.
    """
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)

    workspace, err = _resolve_workspace_from_token(request, body)
    if err is not None:
        return err

    head = (body.get("head") or "").strip()
    if not head:
        return JsonResponse(
            {"error": "field 'head' is required (e.g. 'mba' → head-mba)"}, status=400
        )
    agent_name = head if head.startswith("head-") else f"head-{head}"

    # Use the module's internal helpers so behaviour matches the
    # heartbeat-path dispatch. Force-fire path: skip streak/cooldown,
    # call _run_pick_todo + _post_dispatch_message directly.
    from hub import auto_dispatch as ad
    from hub.registry import _agents, _lock

    host = ad._head_host_from_name(agent_name)
    if host is None:
        return JsonResponse(
            {"error": f"agent {agent_name} is not a head-* agent"}, status=400
        )
    lane = ad.LANE_FOR_HOST.get(host, "")

    override_todo = body.get("todo")
    pick = None
    if override_todo is not None:
        try:
            pick = {
                "number": int(override_todo),
                "title": (body.get("todo_title") or "").strip()
                or f"manual dispatch of todo#{int(override_todo)}",
                "labels": [lane] if lane else [],
                "reason": "operator-override",
            }
        except (TypeError, ValueError):
            return JsonResponse(
                {"error": "field 'todo' must be an integer"}, status=400
            )
    elif lane:
        pick = ad._run_pick_todo(lane)

    now = time.time()
    with _lock:
        agent = _agents.get(agent_name)
        if agent is None:
            return JsonResponse(
                {
                    "error": f"agent {agent_name} not in registry (not connected?)",
                    "head": head,
                },
                status=404,
            )
        workspace_id = agent.get("workspace_id") or workspace.id
        # Arm cooldown + reset streak so the heartbeat path doesn't
        # double-fire right after this manual dispatch.
        agent["auto_dispatch_last_fire_ts"] = now
        agent["idle_streak"] = 0
        streak = 0

    streak_for_text = 0  # forced fire — not from a streak
    cooldown_s = ad._cooldown_seconds()
    text = ad._compose_dispatch_text(streak_for_text, pick, cooldown_s)
    metadata = {
        "kind": "auto-dispatch",
        "agent": agent_name,
        "lane": lane,
        "streak": streak_for_text,
        "todo_number": (pick or {}).get("number"),
        "todo_title": (pick or {}).get("title"),
        "trigger": "manual",
        "reason": body.get("reason") or "operator-manual",
    }

    msg_id = ad._post_dispatch_message(
        agent_name, int(workspace_id), text, metadata
    )
    log.info(
        "auto_dispatch.fire: manual agent=%s lane=%s todo=%s msg=%s",
        agent_name,
        lane,
        (pick or {}).get("number"),
        msg_id,
    )
    return JsonResponse(
        {
            "status": "ok",
            "decision": "fired",
            "agent": agent_name,
            "lane": lane,
            "pick": pick,
            "message_id": msg_id,
            "streak": streak,
        }
    )


# ---------------------------------------------------------------------------
# GET /api/auto-dispatch/status/
# ---------------------------------------------------------------------------

@require_GET
def api_auto_dispatch_status(request):
    """Per-head auto-dispatch streak + cooldown state.

    Returns an array with one entry per ``head-*`` agent::

        [
          {
            "agent": "head-mba",
            "host":  "mba",
            "lane":  "infrastructure",
            "idle_streak": 0,
            "orochi_subagent_count": 2,
            "last_fire_ts": null,                   # unix seconds or null
            "last_fire_at": null,                   # ISO-8601 or null
            "cooldown_active": false,
            "cooldown_remaining_s": 0,
            "streak_threshold": 2,
            "cooldown_seconds": 900
          },
          ...
        ]

    Read-only — does NOT mutate any state.
    """
    workspace, err = _resolve_workspace_from_token(request)
    if err is not None:
        return err

    from hub import auto_dispatch as ad
    from hub.registry import _agents, _lock

    threshold = ad._streak_threshold()
    cooldown_s = ad._cooldown_seconds()
    now = time.time()

    rows: list[dict] = []
    with _lock:
        for name, a in _agents.items():
            if a.get("workspace_id") != workspace.id:
                continue
            host = ad._head_host_from_name(name)
            if host is None:
                continue
            lane = ad.LANE_FOR_HOST.get(host, "")
            last_fire = a.get("auto_dispatch_last_fire_ts")
            last_fire_ts = float(last_fire) if last_fire else None
            cooldown_active = False
            cooldown_remaining = 0
            if last_fire_ts is not None:
                elapsed = now - last_fire_ts
                if elapsed < cooldown_s:
                    cooldown_active = True
                    cooldown_remaining = int(max(0, cooldown_s - elapsed))
            last_fire_at = None
            if last_fire_ts is not None:
                last_fire_at = datetime.fromtimestamp(
                    last_fire_ts, tz=timezone.utc
                ).isoformat()
            rows.append(
                {
                    "agent": name,
                    "host": host,
                    "lane": lane,
                    "idle_streak": int(a.get("idle_streak") or 0),
                    "orochi_subagent_count": int(a.get("orochi_subagent_count") or 0),
                    "last_fire_ts": last_fire_ts,
                    "last_fire_at": last_fire_at,
                    "cooldown_active": cooldown_active,
                    "cooldown_remaining_s": cooldown_remaining,
                    "streak_threshold": threshold,
                    "cooldown_seconds": cooldown_s,
                }
            )
    rows.sort(key=lambda r: r["agent"])
    return JsonResponse(rows, safe=False)
