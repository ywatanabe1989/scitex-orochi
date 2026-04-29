"""Channel/workspace listing + prefs + members + stats API views."""

from hub.views._helpers import resolve_workspace_and_actor
from hub.views.api._common import (
    Channel,
    ChannelPreference,
    JsonResponse,
    Workspace,
    WorkspaceMember,
    WorkspaceToken,
    async_to_sync,
    csrf_exempt,
    get_channel_layer,
    get_workspace,
    json,
    login_required,
    normalize_channel_name,
    require_GET,
    require_http_methods,
    settings,
)


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


@csrf_exempt
@require_http_methods(["GET", "PATCH"])
def api_channels(request, slug=None):
    """GET /api/channels/ — list channels in current workspace.
    PATCH /api/channels/?name=<channel> — update channel description (topic).

    Auth: Django session OR workspace token (``?token=wks_...``). The
    token branch supports the MCP ``channel_info`` tool which hits the
    bare domain — see issue #254 / #258 for the original outage. PATCH
    still requires a logged-in human (token-auth has no notion of "who
    edited the topic").
    """
    # GET supports token auth (read-only); PATCH still requires session
    # because we attribute the edit to a Django user for audit.
    if request.method == "GET":
        token_str = request.GET.get("token")
        if token_str:
            try:
                wt = WorkspaceToken.objects.select_related("workspace").get(
                    token=token_str
                )
                workspace = wt.workspace
            except WorkspaceToken.DoesNotExist:
                return JsonResponse({"error": "invalid token"}, status=401)
        elif request.user and request.user.is_authenticated:
            workspace = get_workspace(request, slug=slug)
        else:
            return JsonResponse({"error": "auth required"}, status=401)
    else:
        if not (request.user and request.user.is_authenticated):
            return JsonResponse({"error": "auth required"}, status=401)
        workspace = get_workspace(request, slug=slug)

    if request.method == "PATCH":
        body = json.loads(request.body)
        ch_name = normalize_channel_name(body.get("name", ""))
        try:
            ch = Channel.objects.get(workspace=workspace, name=ch_name)
        except Channel.DoesNotExist:
            return JsonResponse({"error": "channel not found"}, status=404)
        changed = []
        if "description" in body:
            ch.description = body.get("description", "")
            changed.append("description")
        for field in ("icon_emoji", "icon_image", "icon_text", "color"):
            if field in body:
                setattr(ch, field, body.get(field) or "")
                changed.append(field)
        # is_archived requires admin/superuser — regular users get 403.
        if "is_archived" in body:
            if not (request.user.is_superuser or request.user.is_staff):
                return JsonResponse({"error": "permission denied"}, status=403)
            ch.is_archived = bool(body["is_archived"])
            changed.append("is_archived")
        if changed:
            ch.save(update_fields=changed)
        # Broadcast identity so every client updates sidebar / pool chip / canvas.
        layer = get_channel_layer()
        group = f"workspace_{workspace.id}"
        async_to_sync(layer.group_send)(
            group,
            {
                "type": "channel.identity",
                "channel": ch_name,
                "description": ch.description,
                "icon_emoji": ch.icon_emoji,
                "icon_image": ch.icon_image,
                "icon_text": ch.icon_text,
                "color": ch.color,
                "is_archived": ch.is_archived,
            },
        )
        return JsonResponse(
            {
                "status": "ok",
                "channel": ch_name,
                "description": ch.description,
                "icon_emoji": ch.icon_emoji,
                "icon_image": ch.icon_image,
                "icon_text": ch.icon_text,
                "color": ch.color,
                "is_archived": ch.is_archived,
            }
        )

    channels = Channel.objects.filter(workspace=workspace).order_by("name")
    # Annotate with user preferences when authenticated
    prefs_map = {}
    if request.user.is_authenticated:
        for p in ChannelPreference.objects.filter(
            user=request.user, channel__workspace=workspace
        ):
            prefs_map[p.channel_id] = p
    data = []
    for ch in channels:
        p = prefs_map.get(ch.id)
        data.append(
            {
                "name": ch.name,
                "description": ch.description,
                "icon_emoji": ch.icon_emoji,
                "icon_image": ch.icon_image,
                "icon_text": ch.icon_text,
                "color": ch.color,
                "is_archived": ch.is_archived,
                "is_starred": p.is_starred if p else False,
                "is_muted": p.is_muted if p else False,
                "is_hidden": p.is_hidden if p else False,
                "notification_level": p.notification_level if p else "all",
            }
        )
    return JsonResponse(data, safe=False)


@csrf_exempt
@login_required
@require_http_methods(["GET", "PATCH"])
def api_channel_prefs(request, slug=None):
    """GET /api/channel-prefs/ — list all channel prefs for current user.
    PATCH /api/channel-prefs/ — update prefs for one channel (todo#391).

    PATCH body: {"channel": "#general", "is_starred": true, ...}
    """
    workspace = get_workspace(request, slug=slug)

    if request.method == "PATCH":
        body = json.loads(request.body)
        ch_name = normalize_channel_name(body.get("channel", ""))
        try:
            ch = Channel.objects.get(workspace=workspace, name=ch_name)
        except Channel.DoesNotExist:
            return JsonResponse({"error": "channel not found"}, status=404)

        pref, _ = ChannelPreference.objects.get_or_create(user=request.user, channel=ch)
        changed_fields = []
        for field in (
            "is_starred",
            "is_muted",
            "is_hidden",
            "notification_level",
            "sort_order",
        ):
            if field in body:
                setattr(pref, field, body[field])
                changed_fields.append(field)
        if changed_fields:
            pref.save(update_fields=changed_fields)

        return JsonResponse(
            {
                "status": "ok",
                "channel": ch_name,
                "is_starred": pref.is_starred,
                "is_muted": pref.is_muted,
                "is_hidden": pref.is_hidden,
                "notification_level": pref.notification_level,
            }
        )

    # GET — return all prefs for current user in this workspace
    prefs = ChannelPreference.objects.filter(
        user=request.user, channel__workspace=workspace
    ).select_related("channel")
    data = [
        {
            "channel": p.channel.name,
            "is_starred": p.is_starred,
            "is_muted": p.is_muted,
            "is_hidden": p.is_hidden,
            "notification_level": p.notification_level,
        }
        for p in prefs
    ]
    return JsonResponse(data, safe=False)


@csrf_exempt
@require_http_methods(["GET", "POST", "PATCH", "DELETE"])
def api_channel_members(request, slug=None):
    """Channel membership admin endpoint (todo#407 + Phase 3 channel refactor).

    GET /api/channel-members/?channel=<name>
        List members with permission level. Read-only; accepts either a
        Django session OR a workspace token (``?token=wks_...&agent=<name>``)
        so the MCP ``channel_members`` tool (#252) can hit it from the
        bare domain without a browser session.
    POST /api/channel-members/  (admin only)
        Subscribe a member: body {channel, username, permission?}.
        Idempotent. Creates the channel if missing (group kind).
    PATCH /api/channel-members/  (admin only)
        Update a member's permission: body {channel, username, permission}.
    DELETE /api/channel-members/  (admin only)
        Unsubscribe a member: body {channel, username}. Idempotent.
    """
    from hub.models import ChannelMembership

    if request.method == "GET":
        workspace, _actor, err = resolve_workspace_and_actor(request, slug=slug)
        if err is not None:
            return err
    else:
        if not (request.user and request.user.is_authenticated):
            return JsonResponse({"error": "auth required"}, status=401)
        workspace = get_workspace(request, slug=slug)

    if request.method in ("POST", "PATCH", "DELETE"):
        body = json.loads(request.body) if request.body else {}
        ch_name = normalize_channel_name(body.get("channel", ""))
        username = body.get("username", "")
        if not ch_name or not username:
            return JsonResponse({"error": "channel and username required"}, status=400)
        # Auth rule (todo#drag-subscribe, ywatanabe 2026-04-19):
        # - Admins (superuser / staff) may subscribe ANY user to any channel.
        # - Any logged-in workspace member may subscribe AGENT accounts
        #   (username prefixed "agent-") to channels in this workspace —
        #   this is the drag-agent-to-channel path on the topology graph,
        #   which shouldn't require staff. Cross-human subscriptions still
        #   need staff.
        is_agent_target = username.startswith("agent-")
        if not (request.user.is_superuser or request.user.is_staff):
            if not is_agent_target:
                return JsonResponse({"error": "permission denied"}, status=403)
        from django.contrib.auth import get_user_model

        User = get_user_model()
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            # For agent targets, auto-create the User row so drag/right-
            # click subscribe succeeds even before the agent has sent
            # its first heartbeat (which is the usual moment when the
            # row gets created by register_agent). ywatanabe 2026-04-19:
            # "right click -> RW; 404 not found" happened when the
            # named agent is registered in the YAML fleet registry but
            # has never pinged the hub yet, so no Django User exists.
            if is_agent_target:
                user = User.objects.create_user(username=username)
            else:
                return JsonResponse({"error": "user not found"}, status=404)

        if request.method == "DELETE":
            try:
                ch = Channel.objects.get(workspace=workspace, name=ch_name)
            except Channel.DoesNotExist:
                return JsonResponse({"status": "ok", "deleted": 0})
            deleted, _ = ChannelMembership.objects.filter(
                user=user, channel=ch
            ).delete()
            return JsonResponse({"status": "ok", "deleted": deleted})

        # msg#16884 bit-split body shape. Callers may send either the
        # legacy ``permission`` enum (still accepted, backwards-compat)
        # OR the two independent bits ``can_read`` / ``can_write``.
        # When both are present the bits win — they are the new
        # authoritative surface, the enum is the one-release deprecation
        # bridge. Missing bits default to True (full read-write), which
        # matches the pre-split default.
        has_can_read = "can_read" in body
        has_can_write = "can_write" in body
        if has_can_read or has_can_write:
            can_read = bool(body.get("can_read", True))
            can_write = bool(body.get("can_write", True))
        else:
            perm = body.get("permission", "read-write")
            if perm not in ("read-write", "read-only", "write-only"):
                return JsonResponse({"error": "invalid permission"}, status=400)
            can_read, can_write = ChannelMembership.perm_to_bits(perm)

        # ``#agent`` was abolished 2026-04-21 (lead directive, PR #293
        # follow-up). Block any subscribe/update attempt at the REST layer
        # so the client gets a real signal instead of a silent 200.
        # DELETE is still allowed above so stale memberships can be cleaned.
        from hub.consumers._helpers import ABOLISHED_AGENT_CHANNELS

        if ch_name in ABOLISHED_AGENT_CHANNELS and request.method in ("POST", "PATCH"):
            return JsonResponse({"error": "channel abolished"}, status=403)

        if request.method == "POST":
            # Idempotent subscribe: create the channel if missing.
            ch, _ = Channel.objects.get_or_create(
                workspace=workspace,
                name=ch_name,
                defaults={"kind": Channel.KIND_GROUP},
            )
        else:
            try:
                ch = Channel.objects.get(workspace=workspace, name=ch_name)
            except Channel.DoesNotExist:
                return JsonResponse({"error": "channel not found"}, status=404)

        m, created = ChannelMembership.objects.get_or_create(
            user=user,
            channel=ch,
            defaults={"can_read": can_read, "can_write": can_write},
        )
        if not created and request.method == "PATCH":
            m.can_read = can_read
            m.can_write = can_write
            m.save(update_fields=["can_read", "can_write"])
        return JsonResponse(
            {
                "status": "ok",
                "username": username,
                "channel": ch_name,
                "permission": m.permission,
                "can_read": m.can_read,
                "can_write": m.can_write,
                "created": created,
            }
        )

    ch_name = request.GET.get("channel", "")
    if not ch_name:
        return JsonResponse({"error": "channel param required"}, status=400)
    ch_name = normalize_channel_name(ch_name)
    try:
        ch = Channel.objects.get(workspace=workspace, name=ch_name)
    except Channel.DoesNotExist:
        return JsonResponse({"error": "channel not found"}, status=404)

    from hub.models import ChannelMembership

    # Explicit memberships — keyed by username, carrying the row itself
    # so the lookup below can surface both the legacy enum AND the new
    # bits (msg#16884 bit-split) without an extra query.
    memberships = {
        m.user.username: m
        for m in ChannelMembership.objects.filter(channel=ch).select_related("user")
    }
    # Only return explicitly subscribed members (not all workspace members).
    # Default policy: agents subscribe to nothing unless explicitly added.
    # ywatanabe directive msg#11866: "デフォルトですべてのエージェントはどこも購読しない"
    data = []
    for m in ChannelMembership.objects.filter(channel=ch).select_related("user"):
        uname = m.user.username
        kind = "agent" if uname.startswith("agent-") else "human"
        try:
            wm = WorkspaceMember.objects.get(workspace=workspace, user=m.user)
            role = wm.role
        except WorkspaceMember.DoesNotExist:
            role = ""
        data.append(
            {
                "username": uname,
                "permission": m.permission,
                "can_read": m.can_read,
                "can_write": m.can_write,
                "kind": kind,
                "role": role,
            }
        )
    # Always include human workspace members (ywatanabe etc.) for visibility
    human_members = WorkspaceMember.objects.filter(workspace=workspace).select_related(
        "user"
    )
    existing = {d["username"] for d in data}
    for wm in human_members:
        uname = wm.user.username
        if uname not in existing and not uname.startswith("agent-"):
            row = memberships.get(uname)
            if row is None:
                perm = "read-write"
                can_read = True
                can_write = True
            else:
                perm = row.permission
                can_read = row.can_read
                can_write = row.can_write
            data.append(
                {
                    "username": uname,
                    "permission": perm,
                    "can_read": can_read,
                    "can_write": can_write,
                    "kind": "human",
                    "role": wm.role,
                }
            )
    return JsonResponse(data, safe=False)


@csrf_exempt
@require_GET
def api_my_subscriptions(request, slug=None):
    """GET /api/me/subscriptions/?token=wks_...&agent=<name>

    Read-only endpoint backing the MCP ``my_subscriptions`` tool (#253).
    Returns the list of channels the calling agent is explicitly
    subscribed to via :class:`ChannelMembership` rows. Each row has the
    shape ``{channel, joined_at, role}`` where ``role`` is the member's
    permission on that channel (``read-write`` / ``read-only``).

    Auth follows the same token-or-session contract as the other
    agent-facing read endpoints (see
    :func:`hub.views._helpers.resolve_workspace_and_actor`). On token
    auth the actor is taken from ``?agent=<name>``; on session auth the
    actor is the logged-in user (so a human dashboard query is also
    valid). Either way the response is scoped to the *actor* — an
    agent cannot peek at another agent's subscriptions.
    """
    from hub.models import ChannelMembership

    workspace, actor_member, err = resolve_workspace_and_actor(request, slug=slug)
    if err is not None:
        return err

    memberships = (
        ChannelMembership.objects.filter(
            user=actor_member.user,
            channel__workspace=workspace,
        )
        .select_related("channel")
        .order_by("channel__name")
    )
    data = [
        {
            "channel": m.channel.name,
            "joined_at": m.joined_at.isoformat() if m.joined_at else None,
            "role": m.permission,
            "can_read": m.can_read,
            "can_write": m.can_write,
        }
        for m in memberships
    ]
    return JsonResponse(data, safe=False)


@login_required
@require_GET
def api_stats(request, slug=None):
    """GET /api/stats/ — workspace statistics."""
    from hub.models import Message

    workspace = get_workspace(request, slug=slug)
    include_archived = request.GET.get("include_archived") == "1"
    channels_qs = Channel.objects.filter(workspace=workspace)
    if not include_archived:
        channels_qs = channels_qs.filter(is_archived=False)
    channels = channels_qs
    msg_count = Message.objects.filter(workspace=workspace).count()
    member_count = WorkspaceMember.objects.filter(workspace=workspace).count()

    # Count online agents from in-memory registry
    from hub.registry import get_online_count

    agents_online = get_online_count(workspace_id=workspace.id)

    # Normalize channel names via the canonical helper, deduplicate,
    # exclude DM channels (they have their own sidebar section).
    # The write-side fix (Channel.save()) makes new rows always canonical;
    # this loop handles legacy rows until migration 0015 backfills them.
    # Use kind field when available, fall back to name prefix as defense.
    seen: set[str] = set()
    unique_channels: list[str] = []
    for ch in channels:
        if ch.kind == Channel.KIND_DM or ch.name.startswith("dm:"):
            continue
        name = normalize_channel_name(ch.name)
        if name not in seen:
            seen.add(name)
            unique_channels.append(name)

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
