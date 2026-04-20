"""Reactions + single-message edit/delete API views.

Split out of ``_messages.py`` to keep each sub-file under 500 lines;
these endpoints operate on an existing message id rather than the
channel-scoped message list.
"""

from hub.views.api._common import (
    JsonResponse,
    Message,
    MessageReaction,
    WorkspaceMember,
    WorkspaceToken,
    async_to_sync,
    csrf_exempt,
    get_channel_layer,
    get_workspace,
    json,
    require_http_methods,
    timezone,
)


@csrf_exempt
@require_http_methods(["GET", "POST", "DELETE"])
def api_reactions(request):
    """Reactions API.

    Supports both session auth (browser) and workspace token auth (agents).
    Token can be passed as ?token= query param.

    GET  /api/reactions/?message_ids=1,2,3 — list reactions grouped per message.
    POST /api/reactions/ {message_id, emoji} — toggle reaction by current user.
    DELETE /api/reactions/ {message_id, emoji} — remove reaction by current user.
    """
    # --- auth: token or session ---
    token_str = request.GET.get("token") or request.POST.get("token")
    wks_token = None
    if token_str:
        try:
            wks_token = WorkspaceToken.objects.select_related("workspace").get(
                token=token_str
            )
        except WorkspaceToken.DoesNotExist:
            return JsonResponse({"error": "invalid token"}, status=401)
    elif not (request.user and request.user.is_authenticated):
        return JsonResponse({"error": "auth required"}, status=401)

    # --- resolve workspace ---
    if wks_token:
        workspace = wks_token.workspace
    else:
        workspace = get_workspace(request)

    if request.method == "GET":
        ids_raw = request.GET.get("message_ids", "")
        try:
            ids = [int(x) for x in ids_raw.split(",") if x.strip().isdigit()]
        except ValueError:
            ids = []
        if not ids:
            return JsonResponse({}, safe=False)
        qs = MessageReaction.objects.filter(
            message__workspace=workspace, message_id__in=ids
        ).values("message_id", "emoji", "reactor", "reactor_type")
        grouped: dict[int, dict[str, list]] = {}
        for r in qs:
            m = grouped.setdefault(r["message_id"], {})
            lst = m.setdefault(r["emoji"], [])
            lst.append({"reactor": r["reactor"], "reactor_type": r["reactor_type"]})
        return JsonResponse(grouped)

    # POST or DELETE — modify
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)
    message_id = body.get("message_id")
    emoji = (body.get("emoji") or "").strip()
    if not message_id or not emoji:
        return JsonResponse({"error": "message_id and emoji required"}, status=400)
    try:
        msg = Message.objects.get(id=message_id, workspace=workspace)
    except Message.DoesNotExist:
        return JsonResponse({"error": "message not found"}, status=404)

    # Determine reactor identity
    if request.user and request.user.is_authenticated:
        reactor = request.user.username
        reactor_type = "human"
    else:
        reactor = body.get("reactor") or body.get("agent") or "agent"
        reactor_type = "agent"

    if request.method == "POST":
        obj, created = MessageReaction.objects.get_or_create(
            message=msg,
            emoji=emoji,
            reactor=reactor,
            defaults={"reactor_type": reactor_type},
        )
        action = "added" if created else "existed"
    else:  # DELETE
        deleted, _ = MessageReaction.objects.filter(
            message=msg, emoji=emoji, reactor=reactor
        ).delete()
        action = "removed" if deleted else "not_found"

    # Broadcast reaction update to workspace group
    layer = get_channel_layer()
    group = f"workspace_{workspace.id}"
    async_to_sync(layer.group_send)(
        group,
        {
            "type": "reaction.update",
            "message_id": msg.id,
            "emoji": emoji,
            "reactor": reactor,
            "action": action,
        },
    )
    return JsonResponse({"status": "ok", "action": action})


@csrf_exempt
@require_http_methods(["PATCH", "DELETE"])
def api_message_detail(request, message_id):
    """PATCH/DELETE /api/messages/<id>/ — edit or delete a single message.

    Supports both session auth (browser) and workspace token auth (agents).
    Only the original sender can edit. Only the original sender or an admin
    can delete.
    """
    # --- auth: token or session ---
    token_str = request.GET.get("token") or request.POST.get("token")
    wks_token = None
    acting_user = None
    is_admin = False

    if token_str:
        try:
            wks_token = WorkspaceToken.objects.select_related("workspace").get(
                token=token_str
            )
        except WorkspaceToken.DoesNotExist:
            return JsonResponse({"error": "invalid token"}, status=401)
    elif not (request.user and request.user.is_authenticated):
        return JsonResponse({"error": "auth required"}, status=401)

    # --- resolve workspace + acting identity ---
    if wks_token:
        workspace = wks_token.workspace
        # For token auth, the sender identity comes from the request body
        try:
            body = json.loads(request.body or b"{}")
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "invalid json"}, status=400)
        acting_user = body.get("sender") or body.get("agent") or "agent"
    else:
        workspace = get_workspace(request)
        acting_user = request.user.username
        is_admin = (
            request.user.is_superuser
            or WorkspaceMember.objects.filter(
                user=request.user, workspace=workspace, role="admin"
            ).exists()
        )
        try:
            body = json.loads(request.body or b"{}")
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "invalid json"}, status=400)

    # --- fetch message ---
    try:
        msg = Message.objects.select_related("channel").get(
            id=message_id, workspace=workspace
        )
    except Message.DoesNotExist:
        return JsonResponse({"error": "message not found"}, status=404)

    if request.method == "PATCH":
        # Only the original sender can edit
        if msg.sender != acting_user:
            return JsonResponse(
                {"error": "only the original sender can edit"}, status=403
            )
        new_text = body.get("text") or body.get("content")
        if new_text is None:
            return JsonResponse({"error": "text required"}, status=400)

        msg.content = new_text
        msg.edited = True
        msg.edited_at = timezone.now()
        msg.save(update_fields=["content", "edited", "edited_at"])

        # Broadcast edit event
        layer = get_channel_layer()
        group = f"workspace_{workspace.id}"
        async_to_sync(layer.group_send)(
            group,
            {
                "type": "message.edit",
                "message_id": msg.id,
                "sender": msg.sender,
                "channel": msg.channel.name,
                "text": new_text,
                "edited_at": msg.edited_at.isoformat(),
            },
        )
        return JsonResponse(
            {
                "status": "ok",
                "id": msg.id,
                "edited": True,
                "edited_at": msg.edited_at.isoformat(),
            }
        )

    else:  # DELETE
        # Only the original sender or an admin can delete
        if msg.sender != acting_user and not is_admin:
            return JsonResponse(
                {"error": "only the original sender or admin can delete"},
                status=403,
            )
        msg_id = msg.id
        channel_name = msg.channel.name

        # Soft-delete: retain for 30 days, then hard-delete via management command
        msg.deleted_at = timezone.now()
        msg.save(update_fields=["deleted_at"])

        # Broadcast delete event
        layer = get_channel_layer()
        group = f"workspace_{workspace.id}"
        async_to_sync(layer.group_send)(
            group,
            {
                "type": "message.delete",
                "message_id": msg_id,
                "sender": acting_user,
                "channel": channel_name,
            },
        )
        return JsonResponse({"status": "ok", "id": msg_id, "deleted": True})
