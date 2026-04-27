"""Agent registry read + profile/health/orochi_subagents/purge/pin views."""

from hub.views.api._common import (
    JsonResponse,
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
                    "orochi_machine": p.orochi_machine,
                    "role": p.role,
                    "orochi_model": "",
                    "orochi_multiplexer": "",
                    "orochi_workdir": "",
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
                    "orochi_metrics": {},
                    "orochi_current_task": "",
                    "last_message_preview": "",
                    "orochi_subagents": [],
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
def api_orochi_subagents_update(request):
    """POST /api/orochi_subagents/update — bulk set orochi_subagents for one or more agents.

    Intended for caduceus (and any future process-inspector) that can
    enumerate parent→child claude process trees across the fleet and
    push the result here so the Activity tab renders a live subagent
    tree without requiring every agent to cooperate.

    JSON body (either shape):
        {"token": "wks_...", "agent": "head@mba",
         "orochi_subagents": [{"name": "...", "task": "...", "status": "running"}]}

    or bulk:
        {"token": "wks_...", "updates": [
            {"agent": "head@mba", "orochi_subagents": [...]},
            {"agent": "head@nas", "orochi_subagents": [...]}
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

    from hub.registry import set_orochi_subagents

    updates = body.get("updates")
    if not updates:
        single_agent = body.get("agent")
        if not single_agent:
            return JsonResponse({"error": "agent or updates required"}, status=400)
        updates = [{"agent": single_agent, "orochi_subagents": body.get("orochi_subagents") or []}]

    applied = 0
    for u in updates:
        name = (u.get("agent") or "").strip()
        if not name:
            continue
        set_orochi_subagents(name, u.get("orochi_subagents") or [])
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

    POST body: {"name": "agent-name", "role": "...", "orochi_machine": "...", "icon_emoji": "..."}
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
                "orochi_machine": body.get("orochi_machine", ""),
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
            "orochi_machine": p.orochi_machine,
            "icon_emoji": p.icon_emoji,
            "added_at": p.added_at.isoformat() if p.added_at else None,
        }
        for p in pins
    ]
    return JsonResponse(data, safe=False)

