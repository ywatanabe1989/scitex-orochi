"""A2A protocol dispatch bridge — NAS Django → orochi hub → live agent.

Wires the canonical A2A capability surface at ``a2a.scitex.ai`` into
the running fleet of agents on the orochi hub:

* :func:`api_a2a_dispatch` — POST entry: NAS Django proxies inbound
  A2A JSON-RPC here. Two transports, in priority order:

  1. **HTTP-direct (Tier 3 same-host optimization)** — if the registry
     has an ``a2a_url`` for the agent, the hub HTTPs directly there
     with a short timeout. Fast path; no WS round-trip, no reply
     correlation. Used when the agent runs a sidecar A2A server (sac
     ``spec.a2a.port`` or tier3-ws-bridge with announced url).
  2. **WS dispatch (cross-host fallback)** — fall back to the
     persistent WebSocket transport: ``group_send`` to the per-agent
     Channels group, agent receives, processes, POSTs back to
     ``api_a2a_reply``, the dispatch waiter unblocks. Required for
     agents behind NAT (most fleet hosts) since outbound-WS is the
     only universal transport without per-agent tunnel ops.

* :func:`api_a2a_reply` — POST callback for the WS path: the agent's
  WS-bridge calls this to deliver the reply, which unblocks the
  dispatch waiter.

Reply correlation (WS path only) uses an in-process ``asyncio.Event``
map keyed by a random ``reply_id``. This works because the hub today
is a single process; if it ever scales horizontally, the map moves
to Redis pub/sub. The HTTP-direct path doesn't need this — the agent
returns the response synchronously.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
import urllib.error
import urllib.request
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

log = logging.getLogger("orochi.a2a")

# In-process reply correlation. Each entry is set by api_a2a_reply
# and awaited by api_a2a_dispatch. Cleared in the dispatch view's
# finally block to avoid leaks.
_PENDING: dict[str, dict[str, Any]] = {}

DISPATCH_TIMEOUT_SECONDS = 30.0
HTTP_DIRECT_TIMEOUT_SECONDS = 25.0


def _try_http_direct(a2a_url: str, body: dict[str, Any]) -> tuple[bool, dict | None]:
    """Try HTTP POST to the agent's a2a_url. Return (ok, parsed_response)."""
    try:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            a2a_url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=HTTP_DIRECT_TIMEOUT_SECONDS) as resp:
            return True, json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        log.info("a2a HTTP-direct to %s failed: %s — falling back to WS", a2a_url, exc)
        return False, None


def _agent_group(workspace_id: int, agent: str) -> str:
    """Match the per-agent group name used by ``AgentConsumer``."""
    return f"agent_{workspace_id}_{agent}"


def _resolve_workspace_id(slug_or_id: str) -> int | None:
    """Resolve a workspace name or numeric id to its DB id.

    The Workspace model has no ``slug`` field — the URL kwarg is named
    ``slug`` for parity with other ``api/workspace/<slug:slug>/...``
    routes, but the DB lookup is by ``name``.
    """
    from hub.models import Workspace

    if slug_or_id.isdigit():
        ws = Workspace.objects.filter(id=int(slug_or_id)).first()
    else:
        ws = Workspace.objects.filter(name=slug_or_id).first()
    return ws.id if ws else None


@csrf_exempt
@require_POST
def api_a2a_dispatch(request, slug: str, agent: str):
    """Forward an A2A JSON-RPC body to ``agent`` on workspace ``slug``.

    Body: the raw A2A JSON-RPC envelope (``{jsonrpc, id, method, params}``).
    Returns: the agent's JSON-RPC reply, or 504 on timeout, or 404 if
    the agent is not currently connected.
    """
    ws_id = _resolve_workspace_id(slug)
    if ws_id is None:
        return JsonResponse({"error": f"workspace not found: {slug}"}, status=404)

    try:
        body = json.loads(request.body.decode() or "{}")
    except (json.JSONDecodeError, ValueError) as exc:
        return JsonResponse({"error": f"bad JSON: {exc}"}, status=400)

    # Tier 3 same-host optimization: if the registry has an a2a_url
    # for this agent, try HTTP-direct first. WS dispatch remains the
    # cross-host fallback transport.
    from hub.registry import _agents  # in-memory registry

    reg_entry = _agents.get(agent) or {}
    a2a_url = (reg_entry.get("a2a_url") or "").strip()
    if a2a_url:
        ok, http_result = _try_http_direct(a2a_url, body)
        if ok and http_result is not None:
            return JsonResponse(http_result, json_dumps_params={"ensure_ascii": False})
        # Else fall through to WS dispatch (logged inside _try_http_direct).

    reply_id = secrets.token_urlsafe(16)
    event = asyncio.Event()
    _PENDING[reply_id] = {"event": event, "value": None, "ts": time.time()}

    layer = get_channel_layer()
    if layer is None:
        del _PENDING[reply_id]
        return JsonResponse({"error": "no channel layer"}, status=503)

    group = _agent_group(ws_id, agent)
    try:
        async_to_sync(layer.group_send)(
            group,
            {
                "type": "a2a.dispatch",
                "reply_id": reply_id,
                "body": body,
            },
        )
    except Exception as exc:  # noqa: BLE001
        del _PENDING[reply_id]
        log.exception("a2a dispatch group_send failed: %s", exc)
        return JsonResponse({"error": f"dispatch failed: {exc}"}, status=502)

    async def _await_reply() -> dict[str, Any] | None:
        try:
            await asyncio.wait_for(event.wait(), timeout=DISPATCH_TIMEOUT_SECONDS)
            return _PENDING[reply_id]["value"]
        except asyncio.TimeoutError:
            return None

    try:
        result = async_to_sync(_await_reply)()
    finally:
        _PENDING.pop(reply_id, None)

    if result is None:
        return JsonResponse(
            {
                "error": (
                    f"timeout waiting {DISPATCH_TIMEOUT_SECONDS:.0f}s "
                    f"for reply from agent {agent!r}"
                ),
            },
            status=504,
        )

    return JsonResponse(result, json_dumps_params={"ensure_ascii": False})


@csrf_exempt
@require_POST
def api_a2a_reply(request):
    """Agent-side callback: deliver an A2A reply by ``reply_id``.

    Body: ``{"reply_id": "...", "result": {...JSON-RPC body...}}``.
    The matching :func:`api_a2a_dispatch` waiter unblocks and returns
    the ``result`` to its caller.
    """
    try:
        body = json.loads(request.body.decode() or "{}")
    except (json.JSONDecodeError, ValueError) as exc:
        return JsonResponse({"error": f"bad JSON: {exc}"}, status=400)

    reply_id = body.get("reply_id")
    result = body.get("result")
    if not reply_id or result is None:
        return JsonResponse({"error": "reply_id and result required"}, status=400)

    pending = _PENDING.get(reply_id)
    if pending is None:
        return JsonResponse({"error": "reply_id unknown or expired"}, status=410)

    pending["value"] = result
    pending["event"].set()
    return JsonResponse({"ok": True, "reply_id": reply_id})
