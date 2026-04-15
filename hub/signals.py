"""Signal handlers that keep ``DMParticipant.identity_name`` in sync.

Spec v3 §2.2 — ``identity_name`` is a denormalized hot-path lookup key
used by the ``chat_message`` ACL filter (PR 2). Whenever the
authoritative identity changes (``AgentProfile.name`` rename for agents,
``User.username`` rename for humans), any ``DMParticipant`` rows whose
``member`` points at the affected principal must have their
``identity_name`` updated in the same transaction.
"""

from __future__ import annotations

from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from hub.models import AgentProfile, DMParticipant


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
