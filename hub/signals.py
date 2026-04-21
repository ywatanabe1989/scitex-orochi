"""Signal handlers that keep ``DMParticipant.identity_name`` in sync.

Spec v3 §2.2 — ``identity_name`` is a denormalized hot-path lookup key
used by the ``chat_message`` ACL filter (PR 2). Whenever the
authoritative identity changes (``AgentProfile.name`` rename for agents,
``User.username`` rename for humans), any ``DMParticipant`` rows whose
``member`` points at the affected principal must have their
``identity_name`` updated in the same transaction.

Issue #282 — ``ChannelMembership`` changes fan out to any live
``AgentConsumer`` so the in-memory ``agent_meta["channels"]`` and the
per-channel group-layer joins stay DB-authoritative under out-of-band
edits (admin REST subscribe, drag-to-channel, Django admin UI).
"""

from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from hub.models import AgentProfile, ChannelMembership, DMParticipant
from hub.registry import list_sibling_channels

log = logging.getLogger(__name__)


@receiver(post_save, sender=AgentProfile)
def _agent_profile_rename(sender, instance: AgentProfile, created, **kwargs):
    """Update ``DMParticipant.identity_name`` when an agent is renamed.

    Agents are surfaced through a synthetic Django ``User`` whose
    username is ``agent-<AgentProfile.name>``. When the profile is
    renamed we cannot rely on the username (those rows live elsewhere);
    we key off the underlying ``WorkspaceMember`` set by matching on
    the *current* username pattern and update any stale
    ``identity_name`` rows in the same workspace/channel namespace.
    """
    if created:
        return
    target = instance.name
    username = f"agent-{target}"
    DMParticipant.objects.filter(
        channel__workspace_id=instance.workspace_id,
        member__user__username=username,
    ).exclude(identity_name=target).update(identity_name=target)


@receiver(post_save, sender=User)
def _user_rename(sender, instance: User, created, **kwargs):
    """Update ``DMParticipant.identity_name`` when a human user is renamed."""
    if created:
        return
    # Human participants use the bare username as identity_name;
    # agent participants use the un-prefixed agent name.
    username = instance.username
    identity = username
    if username.startswith("agent-"):
        identity = username[len("agent-"):]
    DMParticipant.objects.filter(member__user_id=instance.id).exclude(
        identity_name=identity
    ).update(identity_name=identity)


# ---------------------------------------------------------------------------
# Issue #282 — ChannelMembership change → refresh live agent consumers.
# ---------------------------------------------------------------------------

_AGENT_USERNAME_PREFIX = "agent-"


def _broadcast_agent_subs_refresh(
    agent_name: str, workspace_id: int
) -> None:
    """Notify every live AgentConsumer for the affected agent to re-sync.

    Only agent users (synthetic ``agent-<name>`` Django users) drive this
    path; humans are irrelevant because they connect via
    :class:`DashboardConsumer` which reads membership on each delivery.

    Called from ``transaction.on_commit`` so the consumer's DB re-fetch
    observes the committed state (avoids a read-before-commit race).
    """
    layer = get_channel_layer()
    if layer is None:
        return

    channel_names = list_sibling_channels(agent_name)
    if not channel_names:
        return

    payload = {
        "type": "agent.subs_refresh",
        "agent": agent_name,
        "workspace_id": workspace_id,
    }
    for channel_name in channel_names:
        try:
            async_to_sync(layer.send)(channel_name, payload)
        except Exception:  # noqa: BLE001 — best-effort; one bad socket
            # shouldn't mask refreshes to the other sibling connections.
            log.exception(
                "agent.subs_refresh send failed (agent=%s channel=%s)",
                agent_name,
                channel_name,
            )


def _queue_membership_refresh(membership: ChannelMembership) -> None:
    """Extract ``(agent_name, workspace_id)`` then schedule the refresh.

    No-ops for non-agent users. Schedules the dispatch via
    ``transaction.on_commit`` so tests that create ChannelMembership rows
    without an explicit transaction still observe the side effect
    (on_commit runs immediately in autocommit mode).
    """
    try:
        user = membership.user
    except User.DoesNotExist:
        return
    username = getattr(user, "username", "") or ""
    if not username.startswith(_AGENT_USERNAME_PREFIX):
        return
    agent_name = username[len(_AGENT_USERNAME_PREFIX):]

    try:
        workspace_id = membership.channel.workspace_id
    except Exception:  # noqa: BLE001
        log.exception("ChannelMembership signal: missing channel/workspace")
        return

    transaction.on_commit(
        lambda: _broadcast_agent_subs_refresh(agent_name, workspace_id)
    )


@receiver(post_save, sender=ChannelMembership)
def _channel_membership_saved(
    sender, instance: ChannelMembership, created, **kwargs
):
    _queue_membership_refresh(instance)


@receiver(post_delete, sender=ChannelMembership)
def _channel_membership_deleted(
    sender, instance: ChannelMembership, **kwargs
):
    _queue_membership_refresh(instance)
