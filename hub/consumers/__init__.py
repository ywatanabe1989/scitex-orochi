"""WebSocket consumers for agent and dashboard connections.

Routing in ``hub/routing.py`` references consumer classes via
``from hub import consumers`` and ``consumers.AgentConsumer`` /
``consumers.DashboardConsumer``; tests + a few views also import the
module-level helpers (``_sanitize_group``, ``_ensure_agent_member``,
``_persist_agent_subscription``, ...). All of those public names are
re-exported below so the pre-split import surface keeps working.

This module was split out of a 1556-line single-file ``consumers.py``
into a focused package — see:

  - ``_groups``    — channel-layer group-name helpers, fleet-channel
    allowlist, hub→agent ping loop
  - ``_helpers``   — DB-bound ``database_sync_to_async`` helpers shared
    by both consumers
  - ``_persistence`` — shared sync ``save_message_sync`` used by both
    consumers' ``_save_message`` methods
  - ``_agent``     — :class:`AgentConsumer`
  - ``_agent_handlers`` — receive_json sub-handlers for the agent
  - ``_agent_message`` — agent ``message`` frame handler (ACL +
    persistence + fan-out)
  - ``_dashboard`` — :class:`DashboardConsumer`
  - ``_dashboard_message`` — dashboard ``message`` frame handler +
    @mention auto-reply
"""

from ._agent import AgentConsumer
from ._dashboard import DashboardConsumer
from ._groups import (
    _FLEET_CHANNELS,
    PING_INTERVAL_SECONDS,
    RTT_WARN_MS,
    _hub_ping_loop,
    _is_fleet_channel,
    _sanitize_group,
    log,
)
from ._helpers import (
    _ensure_agent_member,
    _is_dm_participant_by_member,
    _is_dm_participant_by_username,
    _load_agent_channel_subs,
    _load_agent_mention_only_channels,
    _load_dm_channel_names,
    _persist_agent_subscription,
    _resolve_user_member_id,
    _resolve_workspace_token,
)
from ._persistence import save_message_sync

__all__ = [
    # Public consumer classes — referenced by hub/routing.py
    "AgentConsumer",
    "DashboardConsumer",
    # Channel-layer / ping-loop primitives
    "PING_INTERVAL_SECONDS",
    "RTT_WARN_MS",
    "_FLEET_CHANNELS",
    "_hub_ping_loop",
    "_is_fleet_channel",
    "_sanitize_group",
    "log",
    # DB-bound helpers (imported by tests + hub.views.api)
    "_ensure_agent_member",
    "_is_dm_participant_by_member",
    "_is_dm_participant_by_username",
    "_load_agent_channel_subs",
    "_load_agent_mention_only_channels",
    "_load_dm_channel_names",
    "_persist_agent_subscription",
    "_resolve_user_member_id",
    "_resolve_workspace_token",
    # Shared message persistence
    "save_message_sync",
]
