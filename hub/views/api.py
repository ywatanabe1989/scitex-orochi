"""REST API views for workspace data."""

import json
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from hub.models import Channel, Message, Workspace, WorkspaceMember
from hub.views._helpers import get_workspace

log = logging.getLogger("orochi.api")


@login_required
@require_GET
def api_workspaces(request):
    """GET /api/workspaces/ — list workspaces the user can access."""
    if request.user.is_superuser:
        workspaces = Workspace.objects.all()
    else:
        ws_ids = WorkspaceMember.objects.filter(user=request.user).values_list(
            "workspace_id", flat=True
        )
        workspaces = Workspace.objects.filter(id__in=ws_ids)

    base = settings.OROCHI_BASE_DOMAIN
    data = [
        {
            "name": ws.name,
            "description": ws.description,
            "url": f"https://{ws.name}.{base}/",
        }
        for ws in workspaces
    ]
    return JsonResponse(data, safe=False)


@login_required
@require_GET
def api_channels(request):
    """GET /api/channels/ — list channels in current workspace."""
    workspace = get_workspace(request)
    channels = Channel.objects.filter(workspace=workspace).order_by("name")
    data = [{"name": ch.name, "description": ch.description} for ch in channels]
    return JsonResponse(data, safe=False)


@login_required
@require_http_methods(["GET", "POST"])
def api_messages(request):
    """GET/POST /api/messages/ — recent messages or send one."""
    workspace = get_workspace(request)

    if request.method == "GET":
        limit = min(int(request.GET.get("limit", "100")), 500)
        msgs = (
            Message.objects.filter(workspace=workspace)
            .select_related("channel")
            .order_by("-ts")[:limit]
        )
        data = [
            {
                "id": m.id,
                "channel": m.channel.name,
                "sender": m.sender,
                "sender_type": m.sender_type,
                "content": m.content,
                "ts": m.ts.isoformat(),
                "metadata": m.metadata,
            }
            for m in msgs
        ]
        return JsonResponse(data, safe=False)

    # POST — send a message
    body = json.loads(request.body)
    # Support both flat format {text, channel} and nested {payload: {content, channel}}
    payload = body.get("payload", {})
    ch_name = body.get("channel") or payload.get("channel") or "#general"
    text = body.get("text") or payload.get("content") or payload.get("text") or ""
    if not text:
        return JsonResponse({"error": "text is required"}, status=400)

    channel, _ = Channel.objects.get_or_create(workspace=workspace, name=ch_name)
    msg = Message.objects.create(
        workspace=workspace,
        channel=channel,
        sender=request.user.username,
        sender_type="human",
        content=text,
    )

    layer = get_channel_layer()
    group = f"workspace_{workspace.id}"
    async_to_sync(layer.group_send)(
        group,
        {
            "type": "chat.message",
            "sender": request.user.username,
            "sender_type": "human",
            "channel": ch_name,
            "text": text,
            "ts": msg.ts.isoformat(),
        },
    )

    return JsonResponse({"status": "ok", "id": msg.id}, status=201)


@login_required
@require_GET
def api_history(request, channel_name):
    """GET /api/history/<channel>/ — channel message history."""
    workspace = get_workspace(request)
    if not channel_name.startswith("#"):
        channel_name = f"#{channel_name}"

    limit = min(int(request.GET.get("limit", "50")), 500)
    since = request.GET.get("since")

    qs = Message.objects.filter(
        workspace=workspace, channel__name=channel_name
    ).order_by("-ts")

    if since:
        qs = qs.filter(ts__gt=since)

    msgs = qs[:limit]
    data = [
        {
            "id": m.id,
            "sender": m.sender,
            "sender_type": m.sender_type,
            "content": m.content,
            "ts": m.ts.isoformat(),
            "metadata": m.metadata,
        }
        for m in msgs
    ]
    return JsonResponse(data, safe=False)


@login_required
@require_GET
def api_stats(request):
    """GET /api/stats/ — workspace statistics."""
    workspace = get_workspace(request)
    channels = Channel.objects.filter(workspace=workspace)
    msg_count = Message.objects.filter(workspace=workspace).count()
    member_count = WorkspaceMember.objects.filter(workspace=workspace).count()

    # Count online agents from in-memory registry
    from hub.registry import get_online_count

    agents_online = get_online_count(workspace_id=workspace.id)

    # Deduplicate channel names (safety measure)
    unique_channels = list(dict.fromkeys(ch.name for ch in channels))

    return JsonResponse(
        {
            "workspace": workspace.name,
            "channels": unique_channels,
            "channel_count": len(unique_channels),
            "channels_active": len(unique_channels),
            "message_count": msg_count,
            "member_count": member_count,
            "agents_online": agents_online,
            "observers_connected": member_count,
        }
    )


@login_required
@require_GET
def api_config(request):
    """GET /api/config — dashboard configuration."""
    workspace = get_workspace(request)
    version = getattr(settings, "OROCHI_VERSION", "0.0.0")
    data = {
        "workspace": workspace.name,
        "version": version,
    }
    # Expose dashboard token if set on workspace
    token = request.GET.get("token", "")
    if token:
        data["dashboard_token"] = token
    return JsonResponse(data)


@csrf_exempt
@require_http_methods(["POST"])
def api_event_tool_use(request):
    """POST /api/events/tool-use/ — receive a tool-use event from a Claude Code hook.

    Hooks (PreToolUse/PostToolUse) on each agent's machine POST here to
    record meaningful activity. Updates the in-memory registry's
    last_action timestamp and current_task. Authenticates via workspace
    token query param so hooks don't need Django sessions.

    Body schema:
        {
          "agent": "head@mba",
          "tool": "Edit",
          "phase": "post",          # "pre" or "post"
          "task": "implement #143", # optional, becomes current_task
          "summary": "edited X.py", # optional, short description
          "ts": "2026-04-09T08:00Z" # optional
        }
    """
    token = request.GET.get("token") or request.POST.get("token")
    if token:
        from hub.models import WorkspaceToken
        try:
            WorkspaceToken.objects.get(token=token)
        except WorkspaceToken.DoesNotExist:
            return JsonResponse({"error": "invalid token"}, status=401)
    elif not (request.user and request.user.is_authenticated):
        return JsonResponse({"error": "auth required"}, status=401)

    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)
    agent = (body.get("agent") or "").strip()
    if not agent:
        return JsonResponse({"error": "agent required"}, status=400)

    from hub.registry import mark_activity, set_current_task
    summary = (body.get("summary") or body.get("tool") or "").strip()[:120]
    mark_activity(agent, action=summary)
    if body.get("task"):
        set_current_task(agent, body.get("task")[:120])
    return JsonResponse({"status": "ok"})


@login_required
@require_GET
def api_watchdog_alerts(request):
    """GET /api/watchdog/alerts/ — current agent staleness alerts.

    Returns agents that need attention: those classified as "stale"
    (>10min silent) or "idle" (>2min silent) AND have an active
    current_task. Designed to be polled by mamba (or any monitoring
    client) to drive automated nudges and escalation.
    """
    workspace = get_workspace(request)
    from hub.registry import get_agents

    agents = get_agents(workspace_id=workspace.id)
    alerts = []
    for a in agents:
        liveness = a.get("liveness") or a.get("status") or "online"
        idle = a.get("idle_seconds")
        task = (a.get("current_task") or "").strip()
        if liveness in ("idle", "stale") and task:
            severity = "stale" if liveness == "stale" else "idle"
            alerts.append(
                {
                    "agent": a["name"],
                    "severity": severity,
                    "liveness": liveness,
                    "idle_seconds": idle,
                    "current_task": task,
                    "machine": a.get("machine", ""),
                    "last_action": a.get("last_action"),
                    "suggested_action": (
                        "escalate" if liveness == "stale" else "nudge"
                    ),
                }
            )
    alerts.sort(key=lambda x: -(x.get("idle_seconds") or 0))
    return JsonResponse(
        {
            "alerts": alerts,
            "count": len(alerts),
            "thresholds": {
                "idle_seconds": 120,
                "stale_seconds": 600,
            },
            "ts": timezone.now().isoformat(),
        }
    )


@login_required
@require_GET
def api_agents(request):
    """GET /api/agents — list agents from in-memory registry + DB fallback."""
    workspace = get_workspace(request)

    # Primary: in-memory registry (has live metadata from WS connections)
    from hub.registry import get_agents

    registry_agents = get_agents(workspace_id=workspace.id)

    # Fallback: also include agents from recent messages not in registry
    cutoff = timezone.now() - timezone.timedelta(hours=2)
    db_agent_names = set(
        Message.objects.filter(
            workspace=workspace,
            sender_type="agent",
            ts__gte=cutoff,
        ).values_list("sender", flat=True)
    )
    registry_names = {a["name"] for a in registry_agents}

    # Add DB-only agents (not currently in registry)
    for name in db_agent_names - registry_names:
        last_msg = (
            Message.objects.filter(
                workspace=workspace, sender=name, sender_type="agent"
            )
            .order_by("-ts")
            .first()
        )
        last_ts = last_msg.ts.isoformat() if last_msg else None
        channels = list(
            set(
                Message.objects.filter(
                    workspace=workspace, sender=name, sender_type="agent"
                )
                .values_list("channel__name", flat=True)
                .distinct()
            )
        )
        registry_agents.append(
            {
                "name": name,
                "agent_id": name,
                "status": "offline",
                "role": "agent",
                "machine": "",
                "model": "",
                "channels": channels,
                "current_task": "",
                "registered_at": last_ts,
                "last_heartbeat": last_ts,
                "metrics": {},
            }
        )
    return JsonResponse(registry_agents, safe=False)


@login_required
@require_GET
def api_agents_registry(request):
    """GET /api/agents/registry — detailed agent registry (same data as api_agents)."""
    return api_agents(request)


@login_required
@require_http_methods(["POST"])
def api_agents_purge(request):
    """POST /api/agents/purge — remove stale/offline agents from registry.

    Accepts optional JSON body:
        {"agent": "agent-name"}  — purge a specific agent
    Without body, purges all offline agents.
    """
    from hub.registry import purge_agent, purge_all_offline

    body = {}
    if request.body:
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            pass

    agent_name = body.get("agent")
    if agent_name:
        found = purge_agent(agent_name)
        if found:
            return JsonResponse({"status": "ok", "purged": [agent_name]})
        return JsonResponse({"status": "not_found", "purged": []}, status=404)

    count = purge_all_offline()
    return JsonResponse({"status": "ok", "purged_count": count})


@login_required
@require_GET
def api_resources(request):
    """GET /api/resources — resource usage aggregated per machine from agent registry."""
    workspace = get_workspace(request)

    from hub.registry import get_agents

    agents = get_agents(workspace_id=workspace.id)

    # Aggregate by machine hostname (fall back to agent name)
    machines: dict[str, dict] = {}
    for a in agents:
        machine = a.get("machine") or a["name"]
        metrics = a.get("metrics") or {}

        if machine not in machines:
            machines[machine] = {
                "machine": machine,
                "status": a.get("status", "unknown"),
                "last_heartbeat": a.get("last_heartbeat"),
                "agents": [],
                "resources": {
                    "cpu_count": metrics.get("cpu_count", 0),
                    "cpu_model": metrics.get("cpu_model", ""),
                    "load_avg_1m": metrics.get("load_avg_1m", 0),
                    "load_avg_5m": metrics.get("load_avg_5m", 0),
                    "load_avg_15m": metrics.get("load_avg_15m", 0),
                    "mem_used_percent": metrics.get("mem_used_percent", 0),
                    "mem_total_mb": metrics.get("mem_total_mb", 0),
                    "mem_free_mb": metrics.get("mem_free_mb", 0),
                    "disk_used_percent": metrics.get("disk_used_percent", 0),
                },
            }

        machines[machine]["agents"].append(a["name"])

        # Update with latest metrics if this agent has fresher data
        if metrics and a.get("status") == "online":
            res = machines[machine]["resources"]
            for key in (
                "cpu_count",
                "cpu_model",
                "load_avg_1m",
                "load_avg_5m",
                "load_avg_15m",
                "mem_used_percent",
                "mem_total_mb",
                "mem_free_mb",
                "disk_used_percent",
            ):
                val = metrics.get(key)
                if val:
                    res[key] = val
            # Prefer online status
            machines[machine]["status"] = "online"
            if a.get("last_heartbeat"):
                machines[machine]["last_heartbeat"] = a["last_heartbeat"]

    return JsonResponse(machines, safe=False)
