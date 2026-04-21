"""Direct-message helpers + ``/api/dms/`` view (spec v3 §4)."""

from hub.views._helpers import resolve_workspace_and_actor
from hub.views.api._common import (
    Channel,
    DMParticipant,
    JsonResponse,
    Message,
    WorkspaceMember,
    async_to_sync,
    csrf_exempt,
    get_channel_layer,
    json,
    log,
    require_http_methods,
)


def _dm_canonical_name(principal_keys):
    """Return the canonical ``dm:<a>|<b>`` channel name for a sorted pair.

    Spec v3 §2.3: DM channel names are ``dm:`` + ``|``-joined sorted
    list of ``<type>:<identity>`` principal keys. Sorting makes the
    name independent of who initiated the DM, so ``get_or_create``
    is naturally idempotent.
    """
    return "dm:" + "|".join(sorted(principal_keys))


def _ensure_dm_channel(workspace, channel_name):
    """Idempotently ensure a ``dm:<principal>|<principal>...`` channel exists.

    Used by the message-post path so that agent↔agent and human↔agent DMs
    "just work" on first send — no pre-flight ``POST /api/dms/`` required.

    Parses the canonical ``dm:<type>:<identity>|...`` channel name,
    resolves each principal to a :class:`WorkspaceMember` (creating the
    synthetic ``agent-<name>`` Django user + membership for agent
    principals that have never been seen before, mirroring
    ``hub/views/auth.py``), then gets-or-creates the Channel row with
    ``kind=KIND_DM`` and one ``DMParticipant`` per principal with
    read-write permission.

    Returns the Channel on success, ``None`` if the name cannot be
    parsed. All database writes happen inside a single transaction so
    partial state is impossible on failure.
    """
    from django.contrib.auth.models import User
    from django.db import transaction

    if not channel_name or not channel_name.startswith("dm:"):
        return None

    raw = channel_name[len("dm:") :]
    if not raw:
        return None
    parts = [p for p in raw.split("|") if p]
    if len(parts) < 2:
        return None

    # Parse into (principal_type, identity, username) triples and reject
    # anything that doesn't fit the <type>:<identity> grammar.
    parsed = []
    for p in parts:
        if ":" not in p:
            return None
        kind, _, identity = p.partition(":")
        identity = identity.strip()
        if not identity:
            return None
        if kind == "agent":
            parsed.append(
                (DMParticipant.PRINCIPAL_AGENT, identity, f"agent-{identity}")
            )
        elif kind == "human":
            parsed.append((DMParticipant.PRINCIPAL_HUMAN, identity, identity))
        else:
            return None

    canonical = _dm_canonical_name([f"{t}:{ident}" for (t, ident, _) in parsed])
    if canonical != channel_name:
        # Name is non-canonical (unsorted or duplicate). Bail rather
        # than silently creating a second row under the wrong name; the
        # caller is expected to always pass the canonical form.
        return None

    created_new = False
    with transaction.atomic():
        channel = Channel.objects.filter(workspace=workspace, name=canonical).first()
        if channel is None:
            channel = Channel(workspace=workspace, name=canonical, kind=Channel.KIND_DM)
            channel.full_clean()
            channel.save()
            created_new = True
        elif channel.kind != Channel.KIND_DM:
            # Defensive: a legacy row created by the pre-fix code path
            # may exist with kind="group". Upgrade it in place so ACL
            # lookups start treating it as a DM.
            channel.kind = Channel.KIND_DM
            channel.save(update_fields=["kind"])

        participant_usernames = []
        for principal_type, identity, username in parsed:
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": (
                        f"{username}@agents.orochi.local"
                        if principal_type == DMParticipant.PRINCIPAL_AGENT
                        else ""
                    ),
                    "is_active": True,
                },
            )
            member, _ = WorkspaceMember.objects.get_or_create(
                user=user,
                workspace=workspace,
                defaults={"role": "member"},
            )
            DMParticipant.objects.get_or_create(
                channel=channel,
                member=member,
                defaults={
                    "principal_type": principal_type,
                    "identity_name": identity,
                },
            )
            participant_usernames.append(username)

    # Broadcast a subscribe-hint on the workspace group so any already-
    # connected DashboardConsumer owned by a participant can self-join
    # the dm:<...> group without reconnecting. Without this, an agent-
    # initiated new DM to an already-logged-in user would not animate
    # or arrive on the dashboard until the user refreshed the page.
    # Best-effort — any failure falls back to the reconnect-refresh path.
    if created_new:
        try:
            layer = get_channel_layer()
            async_to_sync(layer.group_send)(
                f"workspace_{workspace.id}",
                {
                    "type": "dm.subscribe",
                    "channel": canonical,
                    "participant_usernames": participant_usernames,
                },
            )
        except Exception:
            log.exception("dm.subscribe broadcast failed for %s", canonical)

    return channel


def _principal_key_for_member(member):
    """Return ``"agent:<name>"`` or ``"human:<username>"`` for a member."""
    username = member.user.username or ""
    if username.startswith("agent-"):
        return f"agent:{username[len('agent-') :]}"
    return f"human:{username}"


def _resolve_recipient_member(workspace, recipient):
    """Resolve a ``"agent:<name>"`` or ``"human:<username>"`` recipient
    string to a :class:`WorkspaceMember`. Returns ``None`` if the
    recipient is not a member of ``workspace`` or the form is invalid.
    """
    if not recipient or ":" not in recipient:
        return None
    kind, _, identity = recipient.partition(":")
    identity = identity.strip()
    if not identity:
        return None
    if kind == "agent":
        username = f"agent-{identity}"
    elif kind == "human":
        username = identity
    else:
        return None
    return (
        WorkspaceMember.objects.filter(workspace=workspace, user__username=username)
        .select_related("user")
        .first()
    )


def _dm_row(channel, current_member):
    """Build the row dict returned by GET/POST /dms/."""
    others = []
    for p in channel.dm_participants.select_related("member__user"):
        if p.member_id == current_member.id:
            continue
        others.append({"type": p.principal_type, "identity_name": p.identity_name})
    last_msg = (
        Message.objects.filter(channel=channel).order_by("-ts").only("ts").first()
    )
    return {
        "name": channel.name,
        "kind": channel.kind,
        "other_participants": others,
        "last_message_ts": last_msg.ts.isoformat() if last_msg else None,
    }


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_dms(request, slug=None):
    """GET/POST /api/workspace/<slug>/dms/ — list or create 1:1 DMs.

    Spec v3 §4. Auth is either a Django session OR a workspace token
    (``?token=wks_...&agent=<name>``) — see
    :func:`hub.views._helpers.resolve_workspace_and_actor`. MCP sidecars
    on the bare domain rely on the token branch (issue #258 root cause).
    """
    workspace, current_member, err = resolve_workspace_and_actor(request, slug=slug)
    if err is not None:
        return err

    if request.method == "GET":
        my_dm_channel_ids = DMParticipant.objects.filter(
            member=current_member,
            channel__workspace=workspace,
            channel__kind=Channel.KIND_DM,
        ).values_list("channel_id", flat=True)
        channels = Channel.objects.filter(id__in=list(my_dm_channel_ids)).order_by(
            "name"
        )
        rows = [_dm_row(ch, current_member) for ch in channels]
        return JsonResponse({"dms": rows}, safe=False)

    # POST — get-or-create a 1:1 DM
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)
    recipient = (body.get("recipient") or body.get("peer") or "").strip()
    if not recipient:
        return JsonResponse({"error": "recipient required"}, status=400)

    other_member = _resolve_recipient_member(workspace, recipient)
    if other_member is None:
        return JsonResponse(
            {"error": f"recipient {recipient!r} is not a workspace member"},
            status=404,
        )
    if other_member.id == current_member.id:
        return JsonResponse({"error": "cannot DM yourself"}, status=400)

    me_key = _principal_key_for_member(current_member)
    other_key = _principal_key_for_member(other_member)
    canonical_name = _dm_canonical_name([me_key, other_key])

    # Idempotent get-or-create. We do NOT use Channel.objects.get_or_create
    # because we need full_clean() (PR 1 dm: prefix guard) to run on
    # the create path.
    channel = Channel.objects.filter(workspace=workspace, name=canonical_name).first()
    if channel is None:
        channel = Channel(
            workspace=workspace,
            name=canonical_name,
            kind=Channel.KIND_DM,
        )
        channel.full_clean()
        channel.save()

    def _principal_type(member):
        return (
            DMParticipant.PRINCIPAL_AGENT
            if (member.user.username or "").startswith("agent-")
            else DMParticipant.PRINCIPAL_HUMAN
        )

    def _identity_name(member):
        username = member.user.username or ""
        if username.startswith("agent-"):
            return username[len("agent-") :]
        return username

    DMParticipant.objects.get_or_create(
        channel=channel,
        member=current_member,
        defaults={
            "principal_type": _principal_type(current_member),
            "identity_name": _identity_name(current_member),
        },
    )
    DMParticipant.objects.get_or_create(
        channel=channel,
        member=other_member,
        defaults={
            "principal_type": _principal_type(other_member),
            "identity_name": _identity_name(other_member),
        },
    )

    return JsonResponse(_dm_row(channel, current_member), status=200)
