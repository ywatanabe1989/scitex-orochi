"""Agent registry read + profile/health/subagents/purge/pin views."""

from hub.views.api._common import (
    JsonResponse,
    WorkspaceToken,
    csrf_exempt,
    get_workspace,
    json,
    login_required,
    require_GET,
    require_http_methods,
)


@require_GET
def api_agents(request):
    """GET /api/agents — list agents from in-memory registry only.

    Auth: Django session OR workspace token (?token=wks_...) so lightweight
    stdlib agents (e.g. caduceus) can poll without a browser login.
    """
    if not (request.user and request.user.is_authenticated):
        token = request.GET.get("token")
        if not token:
            return JsonResponse({"error": "Authentication required"}, status=401)
        from hub.models import WorkspaceToken

        try:
            WorkspaceToken.objects.get(token=token)
        except WorkspaceToken.DoesNotExist:
            return JsonResponse({"error": "Invalid token"}, status=401)
    workspace = get_workspace(request)

    # In-memory registry is the single source of truth for connected agents.
    # No DB fallback — querying Message senders created ghost entries for
    # agents that had disconnected but sent messages recently.
    from hub.registry import get_agents

    registry_agents = get_agents(workspace_id=workspace.id)

    # Merge pinned agents: any pinned agent not in the live registry
    # is added as an "offline" placeholder so the dashboard always shows
    # the expected team roster.
    from hub.models import PinnedAgent

    live_names = {a["name"] for a in registry_agents}
    pinned = PinnedAgent.objects.filter(workspace=workspace)
    for p in pinned:
        if p.name not in live_names:
            registry_agents.append(
                {
                    "name": p.name,
                    "agent_id": p.name,
                    "machine": p.machine,
                    "role": p.role,
                    "model": "",
                    "multiplexer": "",
                    "workdir": "",
                    "icon": "",
                    "icon_emoji": p.icon_emoji,
                    "icon_text": "",
                    "color": getattr(p, "color", ""),
                    "channels": [],
                    "status": "offline",
                    "liveness": "offline",
                    "idle_seconds": None,
                    "registered_at": None,
                    "last_heartbeat": None,
                    "last_action": None,
                    "metrics": {},
                    "orochi_current_task": "",
                    "last_message_preview": "",
                    "subagents": [],
                    "orochi_subagent_count": 0,
                    "health": {},
                    "orochi_claude_md": "",
                    "pinned": True,
                }
            )

    # Tag live agents that are also pinned
    pinned_names = {p.name for p in pinned}
    for a in registry_agents:
        if "pinned" not in a:
            a["pinned"] = a["name"] in pinned_names

    return JsonResponse(registry_agents, safe=False)


@login_required
@require_GET
def api_agents_registry(request):
    """GET /api/agents/registry — detailed agent registry (same data as api_agents)."""
    return api_agents(request)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_agent_profiles(request):
    """GET / POST persistent per-agent display profiles (icon etc).

    GET  — returns all profiles for the current workspace
    POST — upserts one profile: {name, icon_emoji?, icon_image?, icon_text?}

    Both sessions and workspace tokens are accepted.
    """
    # Auth: session OR workspace token
    token = None
    if not (request.user and request.user.is_authenticated):
        body = {}
        if request.method == "POST" and request.body:
            try:
                body = json.loads(request.body)
            except (json.JSONDecodeError, ValueError):
                body = {}
        token = request.GET.get("token") or (
            body.get("token") if isinstance(body, dict) else None
        )
        if not token:
            return JsonResponse({"error": "Authentication required"}, status=401)
        from hub.models import WorkspaceToken

        try:
            WorkspaceToken.objects.get(token=token)
        except WorkspaceToken.DoesNotExist:
            return JsonResponse({"error": "Invalid token"}, status=401)

    workspace = get_workspace(request)
    from hub.models import AgentProfile

    if request.method == "GET":
        profiles = AgentProfile.objects.filter(workspace=workspace)
        data = [
            {
                "name": p.name,
                "icon_emoji": p.icon_emoji,
                "icon_image": p.icon_image,
                "icon_text": p.icon_text,
                "color": p.color,
                # todo#305 Task 7: expose persistent is_hidden so
                # sidebar + topology can dim / drop the card at load.
                "is_hidden": bool(getattr(p, "is_hidden", False)),
                "updated_at": p.updated_at.isoformat(),
            }
            for p in profiles
        ]
        return JsonResponse(data, safe=False)

    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)
    name = (body.get("name") or "").strip()
    if not name:
        return JsonResponse({"error": "name required"}, status=400)
    # todo#305 Task 7 (lead msg#15548): accept optional is_hidden patch
    # so the 👁 eye toggle on the agent card can flip the persistent
    # hidden flag via the SAME endpoint it already uses for icon /
    # color. Patch semantics: only fields present in the body are
    # touched — existing icon/color are not clobbered by a sole
    # {name, is_hidden} POST.
    defaults = {}
    if "icon_emoji" in body:
        defaults["icon_emoji"] = (body.get("icon_emoji") or "")[:16]
    if "icon_image" in body:
        defaults["icon_image"] = (body.get("icon_image") or "")[:500]
    if "icon_text" in body:
        defaults["icon_text"] = (body.get("icon_text") or "")[:16]
    if "color" in body:
        defaults["color"] = (body.get("color") or "")[:16]
    if "is_hidden" in body:
        defaults["is_hidden"] = bool(body.get("is_hidden"))
    if not defaults:
        # Callers that only send {name} (e.g. touch / refresh pings)
        # still get a valid row back — use setdefault-style update_or_create.
        profile, _ = AgentProfile.objects.get_or_create(
            workspace=workspace, name=name
        )
    else:
        profile, _ = AgentProfile.objects.update_or_create(
            workspace=workspace,
            name=name,
            defaults=defaults,
        )
    # Push into the in-memory registry so the live card updates too
    from hub.registry import _agents, _lock

    with _lock:
        if name in _agents:
            if profile.icon_emoji:
                _agents[name]["icon_emoji"] = profile.icon_emoji
            if profile.icon_image:
                _agents[name]["icon"] = profile.icon_image
            if profile.icon_text:
                _agents[name]["icon_text"] = profile.icon_text
            if profile.color:
                _agents[name]["color"] = profile.color
            _agents[name]["is_hidden"] = bool(profile.is_hidden)
    return JsonResponse(
        {
            "status": "ok",
            "name": name,
            "icon_emoji": profile.icon_emoji,
            "icon_image": profile.icon_image,
            "icon_text": profile.icon_text,
            "color": profile.color,
            "is_hidden": bool(getattr(profile, "is_hidden", False)),
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
def api_agent_health(request):
    """POST /api/agents/health/ — caduceus (or any authorized healer)
    records a diagnosis for one or more agents.

    Single:
        {"token":"wks_...", "agent":"head@mba",
         "status":"healthy|idle|stale|stuck_prompt|dead|ghost|unknown",
         "reason":"Simmering… bypass-perms on",
         "source":"caduceus@mba"}

    Bulk:
        {"token":"wks_...", "updates":[{agent, status, reason, source}, ...]}
    """
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)
    token = body.get("token") or request.GET.get("token")
    if not token:
        return JsonResponse({"error": "token required"}, status=401)
    from hub.models import WorkspaceToken

    try:
        WorkspaceToken.objects.get(token=token)
    except WorkspaceToken.DoesNotExist:
        return JsonResponse({"error": "invalid token"}, status=401)

    from hub.registry import set_health

    updates = body.get("updates")
    if not updates:
        single = body.get("agent")
        if not single:
            return JsonResponse({"error": "agent or updates required"}, status=400)
        updates = [
            {
                "agent": single,
                "status": body.get("status", "unknown"),
                "reason": body.get("reason", ""),
                "source": body.get("source", "caduceus"),
            }
        ]

    applied = 0
    for u in updates:
        name = (u.get("agent") or "").strip()
        if not name:
            continue
        set_health(
            name=name,
            status=u.get("status") or "unknown",
            reason=u.get("reason") or "",
            source=u.get("source") or "caduceus",
        )
        applied += 1
    return JsonResponse({"status": "ok", "applied": applied})


@csrf_exempt
@require_http_methods(["POST"])
def api_subagents_update(request):
    """POST /api/subagents/update — bulk set subagents for one or more agents.

    Intended for caduceus (and any future process-inspector) that can
    enumerate parent→child claude process trees across the fleet and
    push the result here so the Activity tab renders a live subagent
    tree without requiring every agent to cooperate.

    JSON body (either shape):
        {"token": "wks_...", "agent": "head@mba",
         "subagents": [{"name": "...", "task": "...", "status": "running"}]}

    or bulk:
        {"token": "wks_...", "updates": [
            {"agent": "head@mba", "subagents": [...]},
            {"agent": "head@nas", "subagents": [...]}
        ]}
    """
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)
    token = body.get("token") or request.GET.get("token")
    if not token:
        return JsonResponse({"error": "token required"}, status=401)
    from hub.models import WorkspaceToken

    try:
        WorkspaceToken.objects.get(token=token)
    except WorkspaceToken.DoesNotExist:
        return JsonResponse({"error": "invalid token"}, status=401)

    from hub.registry import set_subagents

    updates = body.get("updates")
    if not updates:
        single_agent = body.get("agent")
        if not single_agent:
            return JsonResponse({"error": "agent or updates required"}, status=400)
        updates = [{"agent": single_agent, "subagents": body.get("subagents") or []}]

    applied = 0
    for u in updates:
        name = (u.get("agent") or "").strip()
        if not name:
            continue
        set_subagents(name, u.get("subagents") or [])
        applied += 1
    return JsonResponse({"status": "ok", "applied": applied})


@csrf_exempt
@require_http_methods(["POST"])
def api_agents_purge(request):
    """POST /api/agents/purge — remove stale/offline agents from registry.

    Accepts optional JSON body:
        {"agent": "agent-name"}  — purge a specific agent
    Without body, purges all offline agents.

    Auth: Django session OR workspace token (?token=wks_... or body.token)
    so caduceus can evict ghost entries without a browser session.
    """
    from hub.registry import purge_agent, purge_all_offline

    body = {}
    if request.body:
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            pass

    if not (request.user and request.user.is_authenticated):
        token = request.GET.get("token") or body.get("token")
        if not token:
            return JsonResponse({"error": "Authentication required"}, status=401)
        from hub.models import WorkspaceToken

        try:
            WorkspaceToken.objects.get(token=token)
        except WorkspaceToken.DoesNotExist:
            return JsonResponse({"error": "Invalid token"}, status=401)

    agent_name = body.get("agent")
    if agent_name:
        found = purge_agent(agent_name)
        if found:
            return JsonResponse({"status": "ok", "purged": [agent_name]})
        return JsonResponse({"status": "not_found", "purged": []}, status=404)

    count = purge_all_offline()
    return JsonResponse({"status": "ok", "purged_count": count})


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_agents_pin(request):
    """POST /api/agents/pin/ — pin an agent so it always appears in dashboard.
    DELETE /api/agents/pin/ — unpin an agent.

    POST body: {"name": "agent-name", "role": "...", "machine": "...", "icon_emoji": "..."}
    DELETE body: {"name": "agent-name"}

    Auth: Django session OR workspace token.
    """
    body = {}
    if request.body:
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            pass

    if not (request.user and request.user.is_authenticated):
        token = request.GET.get("token") or body.get("token")
        if not token:
            return JsonResponse({"error": "Authentication required"}, status=401)
        from hub.models import WorkspaceToken

        try:
            WorkspaceToken.objects.get(token=token)
        except WorkspaceToken.DoesNotExist:
            return JsonResponse({"error": "Invalid token"}, status=401)

    workspace = get_workspace(request)
    name = body.get("name", "").strip()
    if not name:
        return JsonResponse({"error": "name is required"}, status=400)

    from hub.models import PinnedAgent

    if request.method == "POST":
        obj, created = PinnedAgent.objects.update_or_create(
            workspace=workspace,
            name=name,
            defaults={
                "role": body.get("role", ""),
                "machine": body.get("machine", ""),
                "icon_emoji": body.get("icon_emoji", ""),
            },
        )
        return JsonResponse(
            {
                "status": "pinned",
                "name": obj.name,
                "created": created,
            }
        )

    # DELETE
    deleted, _ = PinnedAgent.objects.filter(workspace=workspace, name=name).delete()
    if deleted:
        return JsonResponse({"status": "unpinned", "name": name})
    return JsonResponse({"status": "not_found", "name": name}, status=404)


@login_required
@require_GET
def api_agents_pinned(request):
    """GET /api/agents/pinned/ — list all pinned agents for the workspace."""
    workspace = get_workspace(request)
    from hub.models import PinnedAgent

    pins = PinnedAgent.objects.filter(workspace=workspace)
    data = [
        {
            "name": p.name,
            "role": p.role,
            "machine": p.machine,
            "icon_emoji": p.icon_emoji,
            "added_at": p.added_at.isoformat() if p.added_at else None,
        }
        for p in pins
    ]
    return JsonResponse(data, safe=False)


# -- lead-state-handover (ZOO#12) -----------------------------------------
#
# FR-A snapshot upsert/fetch + FR-B owner read + FR-E session-meta lookup.
# All three accept the workspace token via `?token=wks_...` (or POST body)
# so a sac runtime running outside any session can call them.

_SNAPSHOT_AGENT_NAME_MAX = 200
_SNAPSHOT_PAYLOAD_MAX_BYTES = 2 * 1024 * 1024  # 2 MiB hub-side cap


def _resolve_workspace_from_token(request):
    """Return ``(workspace, error_response)`` for a token-only API call.

    Mirrors the pattern in ``api_agent_health`` / ``api_subagents_update``
    but factored out for the lead-state-handover endpoints which are
    invoked from sac runtime code with no Django session in flight.
    """
    body = {}
    if request.method in ("POST", "PUT") and request.body:
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            body = {}
    token = (
        request.GET.get("token")
        or (body.get("token") if isinstance(body, dict) else None)
        or ""
    )
    if not token:
        return None, body, JsonResponse({"error": "token required"}, status=401)
    try:
        tok = WorkspaceToken.objects.get(token=token)
    except WorkspaceToken.DoesNotExist:
        return None, body, JsonResponse({"error": "invalid token"}, status=401)
    return tok.workspace, body, None


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_agent_snapshot(request, name):
    """Lead-state-handover FR-A: upsert/read agent snapshot.

    POST body: ``{"token": "wks_...", "payload": {...}, "owner_host": "<h>"}``
    GET query: ``?token=wks_...`` returns latest payload (404 if none).

    The payload is a free-form JSON blob carrying the agent's memory
    files + recent transcript window — the hub treats it as opaque
    bytes, capped at 2 MiB to keep the table cheap.
    """
    workspace, body, err = _resolve_workspace_from_token(request)
    if err is not None:
        return err
    name = (name or "").strip()
    if not name or len(name) > _SNAPSHOT_AGENT_NAME_MAX:
        return JsonResponse({"error": "invalid agent name"}, status=400)
    from hub.models import AgentSnapshot

    if request.method == "GET":
        try:
            snap = AgentSnapshot.objects.get(workspace=workspace, agent_name=name)
        except AgentSnapshot.DoesNotExist:
            return JsonResponse({"error": "no snapshot"}, status=404)
        return JsonResponse(
            {
                "agent_name": snap.agent_name,
                "owner_host": snap.owner_host,
                "updated_at": snap.updated_at.isoformat(),
                "payload": snap.payload,
            }
        )

    # POST upsert.
    payload = body.get("payload")
    if not isinstance(payload, dict):
        return JsonResponse({"error": "payload must be object"}, status=400)
    # Cheap size guard — Postgres JSONB is happy with large rows but the
    # callsite is a chatty 5-min interval, so reject anything obviously
    # outsized rather than silently grow the table.
    try:
        encoded = json.dumps(payload)
    except (TypeError, ValueError):
        return JsonResponse({"error": "payload not JSON-serialisable"}, status=400)
    if len(encoded) > _SNAPSHOT_PAYLOAD_MAX_BYTES:
        return JsonResponse(
            {"error": f"payload exceeds {_SNAPSHOT_PAYLOAD_MAX_BYTES} bytes"},
            status=413,
        )
    owner_host = (body.get("owner_host") or "")[:200]
    snap, _ = AgentSnapshot.objects.update_or_create(
        workspace=workspace,
        agent_name=name,
        defaults={"payload": payload, "owner_host": owner_host},
    )
    return JsonResponse(
        {
            "status": "ok",
            "agent_name": snap.agent_name,
            "owner_host": snap.owner_host,
            "updated_at": snap.updated_at.isoformat(),
            "bytes": len(encoded),
        }
    )


@require_GET
def api_agent_snapshot_latest(request, name):
    """Lead-state-handover FR-A: GET-only alias for the latest snapshot.

    Provided so sac runtime hydration code can call a stable URL even
    if we later add a multi-snapshot history under the POST endpoint.
    """
    return api_agent_snapshot(request, name)


@require_GET
def api_agent_owner(request, name):
    """Lead-state-handover FR-B: priority-failback owner status.

    Returns:
        {
          "agent": "<name>",
          "current_host": "<host>" | "",
          "priority_list": ["a", "b", "c"],
          "healthy": {"a": false, "b": true, "c": true},
        }

    ``priority_list`` is the YAML ``host:`` list captured by the
    registry on register/heartbeat (see ``hub.registry._register``).
    ``healthy`` is built from ``hub.registry.get_agents`` — a host is
    "healthy" iff at least one agent on that host has a fresh
    heartbeat (idle_seconds within the configured liveness window).
    """
    workspace, _body, err = _resolve_workspace_from_token(request)
    if err is not None:
        return err
    from hub.registry import _agents, _lock, get_agents

    name = (name or "").strip()

    # ``priority_list`` is only carried on the raw in-memory entry —
    # ``get_agents`` strips it before exposing the dashboard payload.
    # Snapshot under the lock so it can't mutate mid-read.
    priority_list: list[str] = []
    current_host = ""
    with _lock:
        raw = _agents.get(name)
        if raw is not None:
            priority_list = list(raw.get("priority_list") or [])
            current_host = (raw.get("machine") or "").strip()

    if not priority_list and current_host:
        priority_list = [current_host]

    # Per-host liveness — any agent on that host with a fresh heartbeat
    # → host is healthy. Stale-heartbeat hosts are unhealthy. We use
    # ``get_agents()`` here (with derived ``liveness``) and bucket per
    # machine.
    healthy = {h: False for h in priority_list}
    if current_host and current_host not in healthy:
        healthy[current_host] = False
    for a in get_agents(workspace_id=workspace.id):
        host = (a.get("machine") or "").strip()
        if not host or host not in healthy:
            continue
        liveness = (a.get("liveness") or "").lower()
        if liveness in ("online", "idle", "active"):
            healthy[host] = True

    return JsonResponse(
        {
            "agent": name,
            "current_host": current_host,
            "priority_list": priority_list,
            "healthy": healthy,
        }
    )


@require_GET
def api_agent_session_meta(request, name, instance_uuid):
    """Lead-state-handover FR-E: resolve ``<name>:<uuid>`` to host/PID.

    Used by the dashboard / debug UI to expand a short-form
    ``lead:8af3`` agent_id stamp into the full hostname + PID + WS
    session id pair, which is invaluable when chasing a rogue-instance
    incident like the one that drove this PR set (ZOO#12).
    """
    workspace, _body, err = _resolve_workspace_from_token(request)
    if err is not None:
        return err
    from hub.models import AgentSession

    try:
        sess = AgentSession.objects.get(
            workspace=workspace, agent_name=name, instance_uuid=instance_uuid
        )
    except AgentSession.DoesNotExist:
        return JsonResponse({"error": "no session"}, status=404)
    return JsonResponse(
        {
            "agent_name": sess.agent_name,
            "instance_uuid": sess.instance_uuid,
            "hostname": sess.hostname,
            "pid": sess.pid,
            "ws_session_id": sess.ws_session_id,
            "cardinality_enforced": sess.cardinality_enforced,
            "connected_at": sess.connected_at.isoformat(),
            "last_heartbeat": sess.last_heartbeat.isoformat(),
            "disconnected_at": (
                sess.disconnected_at.isoformat() if sess.disconnected_at else None
            ),
        }
    )

