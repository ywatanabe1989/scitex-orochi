"""REST API views for workspace data."""

import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_http_methods

from hub.models import Channel, Message, Workspace, WorkspaceMember
from hub.views._helpers import get_workspace


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
                "content": m.content,
                "ts": m.ts.isoformat(),
                "metadata": m.metadata,
            }
            for m in msgs
        ]
        return JsonResponse(data, safe=False)

    # POST — send a message
    body = json.loads(request.body)
    ch_name = body.get("channel", "#general")
    text = body.get("text", "")
    if not text:
        return JsonResponse({"error": "text is required"}, status=400)

    channel, _ = Channel.objects.get_or_create(workspace=workspace, name=ch_name)
    msg = Message.objects.create(
        workspace=workspace,
        channel=channel,
        sender=request.user.username,
        content=text,
    )

    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    layer = get_channel_layer()
    group = f"workspace_{workspace.id}"
    async_to_sync(layer.group_send)(
        group,
        {
            "type": "chat.message",
            "sender": request.user.username,
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

    return JsonResponse(
        {
            "workspace": workspace.name,
            "channels": [ch.name for ch in channels],
            "channel_count": channels.count(),
            "message_count": msg_count,
            "member_count": member_count,
        }
    )
