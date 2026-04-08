"""REST API views for workspace data."""

import json
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
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


@login_required
@require_GET
def api_agents(request):
    """GET /api/agents — list agents from in-memory registry + DB fallback."""
    workspace = get_workspace(request)

    # Primary: in-memory registry (has live metadata from WS connections)
    from hub.registry import get_agents

    registry_agents = get_agents(workspace_id=workspace.id)

    # Fallback: also include agents from recent messages not in registry
    cutoff = timezone.now() - timezone.timedelta(hours=24)
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
@require_GET
def api_resources(request):
    """GET /api/resources — resource usage from agents (empty until agents report)."""
    return JsonResponse({}, safe=True)
