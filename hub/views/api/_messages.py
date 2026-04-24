"""Message send/list, history, threads API views.

Reactions + single-message edit/delete live in :mod:`_reactions` so each
sub-file stays under the 500-line ceiling.
"""

from hub.views.api._common import (
    Channel,
    JsonResponse,
    Message,
    MessageThread,
    async_to_sync,
    check_membership_allowed,
    check_write_allowed,
    get_channel_layer,
    get_workspace,
    json,
    log,
    login_required,
    normalize_channel_name,
    require_GET,
    require_http_methods,
)
from hub.views.api._dms import _ensure_dm_channel


@login_required
@require_http_methods(["GET", "POST"])
def api_messages(request, slug=None):
    """GET/POST /api/messages/ — recent messages or send one."""
    workspace = get_workspace(request, slug=slug)

    if request.method == "GET":
        from django.db.models import Count, Exists, OuterRef

        limit = min(int(request.GET.get("limit", "100")), 500)
        # Exclude messages that are thread replies (they appear in thread panel only)
        is_thread_reply = Exists(MessageThread.objects.filter(reply_id=OuterRef("pk")))
        msgs = (
            Message.objects.filter(workspace=workspace, deleted_at__isnull=True)
            .exclude(is_thread_reply)
            .exclude(channel__name__startswith="dm:")
            .select_related("channel")
            .annotate(thread_count=Count("thread_replies"))
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
                "edited": m.edited,
                "edited_at": m.edited_at.isoformat() if m.edited_at else None,
                "metadata": m.metadata,
                "thread_count": m.thread_count,
            }
            for m in msgs
        ]
        return JsonResponse(data, safe=False)

    # POST — send a message
    body = json.loads(request.body)
    # Support both flat format {text, channel} and nested {payload: {content, channel}}
    payload = body.get("payload", {})
    # Normalize via the canonical helper so write-path and read-path
    # share the same logic. This subsumes the inline 2-line block that
    # landed on develop in parallel.
    ch_name = normalize_channel_name(
        body.get("channel") or payload.get("channel") or "#general"
    )
    text = body.get("text") or payload.get("content") or payload.get("text") or ""
    attachments = payload.get("attachments") or body.get("attachments") or []
    metadata = payload.get("metadata") or body.get("metadata") or {}
    if attachments:
        metadata = {**metadata, "attachments": attachments}
    if not text and not attachments:
        return JsonResponse({"error": "text or attachments required"}, status=400)

    # Lazy-create DM channel + participants BEFORE the ACL check so
    # agent↔agent and human↔agent DMs "just work" on first send without
    # a pre-flight POST /api/dms/. check_write_allowed() denies writes
    # to dm: channels that have no Channel row yet, so without this the
    # very first message between a pair of principals would 403.
    is_dm = ch_name.startswith("dm:")
    if is_dm:
        _ensure_dm_channel(workspace, ch_name)

    # Spec v3 §8 / todo#258: REST POST /messages/ previously bypassed
    # the channel write-ACL that AgentConsumer.receive_json enforces.
    # Mirror the same check here so DM confidentiality (and any
    # channels.yaml ACL) is enforced regardless of transport.
    sender_identity = request.user.username
    if not check_write_allowed(
        sender=sender_identity,
        channel=ch_name,
        workspace_id=workspace.id,
    ):
        return JsonResponse(
            {"error": "not allowed to write to this channel"}, status=403
        )
    # Issue #276 — close the REST write-path ACL gap. The yaml ACL above
    # is permissive-by-default when channels.yaml is absent; the
    # ChannelMembership gate enforces the per-(user, channel) permission
    # rows managed via /api/channel-members/ and blocks agents that were
    # never explicitly subscribed to the target group channel.
    if not check_membership_allowed(
        sender=sender_identity,
        channel=ch_name,
        workspace_id=workspace.id,
    ):
        return JsonResponse(
            {"error": "not a member of this channel"}, status=403
        )

    channel, _ = Channel.objects.get_or_create(
        workspace=workspace,
        name=ch_name,
        defaults={"kind": Channel.KIND_DM if is_dm else Channel.KIND_GROUP},
    )
    msg = Message.objects.create(
        workspace=workspace,
        channel=channel,
        sender=request.user.username,
        sender_type="human",
        content=text,
        metadata=metadata,
    )

    # Spec v3 §3.3 — DMs fan out via channel_<ws>_<name> only, never
    # via the workspace group (which dashboards join without per-channel
    # filtering). Mirror AgentConsumer.receive_json's DM routing so the
    # REST path and WS path deliver DMs identically.
    layer = get_channel_layer()
    kind = "dm" if is_dm else "group"
    if is_dm:
        from hub.consumers import _sanitize_group

        group = _sanitize_group(f"channel_{workspace.id}_{ch_name}")
    else:
        group = f"workspace_{workspace.id}"
    async_to_sync(layer.group_send)(
        group,
        {
            "type": "chat.message",
            "id": msg.id,
            "sender": request.user.username,
            "sender_type": "human",
            "channel": ch_name,
            "kind": kind,
            "text": text,
            "ts": msg.ts.isoformat(),
            "metadata": metadata,
        },
    )

    # Web Push fan-out (todo#263). Best-effort; never block the response.
    try:
        from hub.push import send_push_to_subscribers_async

        send_push_to_subscribers_async(
            workspace_id=workspace.id,
            channel=ch_name,
            sender=request.user.username,
            content=text,
            message_id=msg.id,
        )
    except Exception:
        log.exception("push fan-out failed (REST path)")

    # Cross-channel @mention push (msg#15767). Best-effort — a failure
    # in the helper must not 500 the REST caller. The helper itself
    # no-ops on DM channels and mention-less messages.
    try:
        from hub.mentions import expand_mentions_and_notify

        expand_mentions_and_notify(
            workspace_id=workspace.id,
            source_channel=ch_name,
            source_msg_id=msg.id,
            sender_username=request.user.username,
            text=text,
        )
    except Exception:
        log.exception("mention push fan-out failed (REST path)")

    return JsonResponse({"status": "ok", "id": msg.id}, status=201)


@login_required
@require_GET
def api_history(request, channel_name, slug=None):
    """GET /api/history/<channel>/ — channel message history."""
    workspace = get_workspace(request, slug=slug)
    if not channel_name.startswith("#"):
        channel_name = f"#{channel_name}"

    limit = min(int(request.GET.get("limit", "50")), 500)
    since = request.GET.get("since")

    from django.db.models import Count, Exists, OuterRef

    # Exclude thread replies from main channel feed
    is_thread_reply = Exists(MessageThread.objects.filter(reply_id=OuterRef("pk")))
    qs = (
        Message.objects.filter(
            workspace=workspace, channel__name=channel_name, deleted_at__isnull=True
        )
        .exclude(is_thread_reply)
        .annotate(thread_count=Count("thread_replies"))
        .order_by("-ts")
    )

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
            "edited": m.edited,
            "edited_at": m.edited_at.isoformat() if m.edited_at else None,
            "metadata": m.metadata,
            "thread_count": m.thread_count,
        }
        for m in msgs
    ]
    return JsonResponse(data, safe=False)


@login_required
@require_http_methods(["GET", "POST"])
def api_threads(request):
    """Thread API — list replies or post a new reply.

    GET  /api/threads/?parent_id=N — list all replies under parent message.
    POST /api/threads/ {parent_id, text, attachments?} — post a reply.
    """
    workspace = get_workspace(request)

    if request.method == "GET":
        try:
            parent_id = int(request.GET.get("parent_id", "0"))
        except ValueError:
            return JsonResponse({"error": "invalid parent_id"}, status=400)
        if not parent_id:
            return JsonResponse({"error": "parent_id required"}, status=400)
        try:
            parent = Message.objects.get(id=parent_id, workspace=workspace)
        except Message.DoesNotExist:
            return JsonResponse({"error": "parent not found"}, status=404)
        thread_rows = (
            MessageThread.objects.filter(parent=parent)
            .select_related("reply", "reply__channel")
            .order_by("ts")
        )
        data = [
            {
                "id": t.reply.id,
                "sender": t.reply.sender,
                "sender_type": t.reply.sender_type,
                "content": t.reply.content,
                "ts": t.reply.ts.isoformat(),
                "metadata": t.reply.metadata,
            }
            for t in thread_rows
        ]
        return JsonResponse(data, safe=False)

    # POST — create a threaded reply
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)
    parent_id = body.get("parent_id")
    text = body.get("text") or ""
    attachments = body.get("attachments") or []
    if not parent_id or (not text and not attachments):
        return JsonResponse(
            {"error": "parent_id and text/attachments required"}, status=400
        )
    try:
        parent = Message.objects.get(id=parent_id, workspace=workspace)
    except Message.DoesNotExist:
        return JsonResponse({"error": "parent not found"}, status=404)

    metadata = {}
    if attachments:
        metadata["attachments"] = attachments
    reply = Message.objects.create(
        workspace=workspace,
        channel=parent.channel,
        sender=request.user.username,
        sender_type="human",
        content=text,
        metadata=metadata,
    )
    MessageThread.objects.create(parent=parent, reply=reply)

    layer = get_channel_layer()
    # Send to channel-specific group, not workspace-wide.
    # Fixes reply leak: replies were broadcast to ALL agents regardless
    # of channel subscription (ywatanabe msg#12174/#12176).
    ch_name = parent.channel.name
    channel_group = f"channel_{workspace.id}_{ch_name}"
    # Sanitize for Django Channels group name constraints
    import re

    channel_group = re.sub(r"[^a-zA-Z0-9._-]", "_", channel_group)
    channel_group = re.sub(r"_{3,}", "__", channel_group)
    event = {
        "type": "thread.reply",
        "parent_id": parent.id,
        "reply_id": reply.id,
        "sender": request.user.username,
        "sender_type": "human",
        "channel": ch_name,
        "text": text,
        "ts": reply.ts.isoformat(),
        "metadata": metadata,
    }
    async_to_sync(layer.group_send)(channel_group, event)
    # Also send to workspace group for dashboard observers
    ws_group = f"workspace_{workspace.id}"
    async_to_sync(layer.group_send)(ws_group, event)
    return JsonResponse({"status": "ok", "reply_id": reply.id}, status=201)
