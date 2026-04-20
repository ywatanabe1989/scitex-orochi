"""Database-bound async helpers shared by the AgentConsumer and
DashboardConsumer.

Each ``@database_sync_to_async`` function below was originally defined
at module scope in ``hub/consumers.py``; they are kept as module-level
functions (not methods) so tests and views can import them directly:

    from hub.consumers import _ensure_agent_member, _sanitize_group, ...

The names are re-exported from ``hub/consumers/__init__.py`` for backward
compatibility with the pre-split import surface.
"""

from __future__ import annotations

import re

from channels.db import database_sync_to_async

from hub.models import (
    Channel,
    ChannelMembership,
    DMParticipant,
    Workspace,
    WorkspaceMember,
    WorkspaceToken,
)


@database_sync_to_async
def _load_agent_channel_subs(workspace_id, agent_name):
    """Return the list of channel names this agent is persistently
    subscribed to in the given workspace.

    Agent subscriptions live in :class:`ChannelMembership` rows keyed to
    the agent's synthetic ``agent-<name>`` Django user. An agent is
    considered subscribed iff a ``ChannelMembership`` row exists; the
    row's ``permission`` column governs read-only vs read-write.
    """
    from django.contrib.auth.models import User

    safe_name = re.sub(r"[^a-zA-Z0-9_.\-]", "-", agent_name or "anonymous-agent")
    username = f"agent-{safe_name}"
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return []
    memberships = ChannelMembership.objects.filter(
        user=user,
        channel__workspace_id=workspace_id,
    ).select_related("channel")
    return [m.channel.name for m in memberships]


@database_sync_to_async
def _persist_agent_subscription(workspace_id, agent_name, ch_name, subscribe):
    """Add or remove a persistent ``ChannelMembership`` row for an agent.

    Returns True on success, False if the channel or agent user cannot
    be resolved. Creates the channel if missing (group kind).
    """
    from django.contrib.auth.models import User

    try:
        workspace = Workspace.objects.get(id=workspace_id)
    except Workspace.DoesNotExist:
        return False

    safe_name = re.sub(r"[^a-zA-Z0-9_.\-]", "-", agent_name or "anonymous-agent")
    username = f"agent-{safe_name}"
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={
            "email": f"{username}@agents.orochi.local",
            "is_active": True,
            "is_staff": False,
        },
    )
    channel, _ = Channel.objects.get_or_create(
        workspace=workspace,
        name=ch_name,
        defaults={"kind": Channel.KIND_GROUP},
    )
    if subscribe:
        ChannelMembership.objects.update_or_create(
            user=user,
            channel=channel,
            defaults={"permission": ChannelMembership.PERM_READ_WRITE},
        )
    else:
        ChannelMembership.objects.filter(user=user, channel=channel).delete()
    return True


@database_sync_to_async
def _ensure_agent_member(workspace_id, agent_name):
    """Idempotently ensure a ``WorkspaceMember`` row exists for an agent.

    Mirrors the synthetic-user pattern from ``hub/views/auth.py`` —
    ``agent-<name>`` Django ``User`` + ``WorkspaceMember`` row. Required
    by spec v3 §2.3 so DMParticipant FKs have a stable target.

    Returns the ``WorkspaceMember`` instance (or ``None`` on failure).
    """
    from django.contrib.auth.models import User

    try:
        workspace = Workspace.objects.get(id=workspace_id)
    except Workspace.DoesNotExist:
        return None

    safe_name = re.sub(r"[^a-zA-Z0-9_.\-]", "-", agent_name or "anonymous-agent")
    username = f"agent-{safe_name}"
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={
            "email": f"{username}@agents.orochi.local",
            "is_active": True,
            "is_staff": False,
        },
    )
    member, _ = WorkspaceMember.objects.get_or_create(
        user=user,
        workspace=workspace,
        defaults={"role": "member"},
    )
    return member


@database_sync_to_async
def _load_dm_channel_names(workspace_id, member_id):
    """Return canonical ``dm:`` channel names the given member participates in."""
    if member_id is None:
        return []
    return list(
        DMParticipant.objects.filter(
            member_id=member_id,
            channel__workspace_id=workspace_id,
            channel__kind=Channel.KIND_DM,
        ).values_list("channel__name", flat=True)
    )


@database_sync_to_async
def _resolve_user_member_id(user_id, workspace_id):
    """Resolve a Django user + workspace to a ``WorkspaceMember.id``.

    Used by :class:`DashboardConsumer` at connect time so the dashboard
    can subscribe to every DM channel the logged-in user participates
    in (symmetric with :class:`AgentConsumer`'s connect-time DM
    auto-subscribe in spec v3 §3.1). Returns ``None`` when there's no
    matching membership (e.g. superuser viewing a workspace they aren't
    explicitly a member of) — in that case the dashboard joins no DM
    groups and must rely on the confidentiality filter.
    """
    if user_id is None or workspace_id is None:
        return None
    member = WorkspaceMember.objects.filter(
        user_id=user_id, workspace_id=workspace_id
    ).first()
    return member.id if member else None


@database_sync_to_async
def _is_dm_participant_by_member(channel_name, workspace_id, member_id):
    """Check whether ``member_id`` is a participant of the given DM channel."""
    if member_id is None:
        return False
    return DMParticipant.objects.filter(
        channel__workspace_id=workspace_id,
        channel__name=channel_name,
        channel__kind=Channel.KIND_DM,
        member_id=member_id,
    ).exists()


@database_sync_to_async
def _is_dm_participant_by_username(channel_name, workspace_id, username):
    """Check DM participation for a (possibly unauthenticated) dashboard user.

    ``username=None`` always returns ``False`` — unauthenticated dashboards
    can never read DMs.
    """
    if not username:
        return False
    return DMParticipant.objects.filter(
        channel__workspace_id=workspace_id,
        channel__name=channel_name,
        channel__kind=Channel.KIND_DM,
        member__user__username=username,
    ).exists()


@database_sync_to_async
def _resolve_workspace_token(token_str):
    """Resolve a workspace token string to workspace info dict, or None."""
    if not token_str:
        return None
    try:
        wt = WorkspaceToken.objects.select_related("workspace").get(token=token_str)
        return {
            "workspace_id": wt.workspace_id,
            "workspace_name": wt.workspace.name,
        }
    except WorkspaceToken.DoesNotExist:
        return None
