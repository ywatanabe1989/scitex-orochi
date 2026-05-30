"""Core models for the Orochi communication hub.

Split out of a 699-line single-file ``hub/models.py`` into focused
sub-modules — ``_identity`` (workspaces, members, profiles, invites),
``_messaging`` (channels, messages, reactions, threads),
``_agents`` (pinned/container/scheduled), and ``_misc`` (push, fleet
reports, tracked repos). The pre-split public surface is re-exported
here so ``from hub.models import X`` keeps working unchanged, and
Django's app-loader picks every Model class up via this ``__init__``.

Each model carries an explicit ``Meta.app_label = "hub"`` so the
existing ``hub/migrations/`` history continues to resolve to the same
``hub.<ModelName>`` references with zero migration delta.
"""

from ._agents import (
    AgentGroup,
    AgentSession,
    AgentSnapshot,
    ContainerAgent,
    PinnedAgent,
    ScheduledAction,
)
from ._helpers import _generate_workspace_token, normalize_channel_name
from ._identity import (
    AgentProfile,
    InviteRequest,
    UserProfile,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMember,
    WorkspaceToken,
)
from ._messaging import (
    Channel,
    ChannelMembership,
    ChannelPreference,
    DMParticipant,
    Message,
    MessageReaction,
    MessageThread,
)
from ._misc import FleetReport, PushSubscription, TrackedRepo

__all__ = [
    # _helpers
    "_generate_workspace_token",
    "normalize_channel_name",
    # _identity
    "AgentProfile",
    "InviteRequest",
    "UserProfile",
    "Workspace",
    "WorkspaceInvitation",
    "WorkspaceMember",
    "WorkspaceToken",
    # _messaging
    "Channel",
    "ChannelMembership",
    "ChannelPreference",
    "DMParticipant",
    "Message",
    "MessageReaction",
    "MessageThread",
    # _agents
    "AgentGroup",
    "AgentSession",
    "AgentSnapshot",
    "ContainerAgent",
    "PinnedAgent",
    "ScheduledAction",
    # _misc
    "FleetReport",
    "PushSubscription",
    "TrackedRepo",
]
