"""In-memory agent registry -- tracks connected agents and their metadata.

AgentConsumer writes to this registry on register/heartbeat/disconnect.
The REST API reads from it for /api/agents and /api/stats.

Active-session tracking (scitex-orochi#144 fix path 4):
A single ``SCITEX_OROCHI_AGENT=<name>`` identity may have multiple
WebSocket connections at once (a known race hazard — two Claude Code
processes booting from the same yaml). The registry tracks the set of
live connection IDs per agent in ``_connections[name]`` so:

  - the dashboard can render a warning when ``active_sessions > 1``;
  - ``unregister_agent()`` only marks offline when the LAST connection
    drops, not when the first of N sibling sessions disconnects.

The connection IDs are opaque strings (Django Channels' ``channel_name``
attribute, unique per WebSocket); the registry treats them as
identifiers, not as data.

This module was split out of a 798-line single-file ``registry.py`` into
a focused package — see ``_store`` (primitives), ``_register`` (registry
mutators with the prev-preserve list), ``_heartbeat`` (heartbeat /
activity / health setters), and ``_payload`` (Agents-tab read path).
The full pre-split public surface is re-exported here so
``from hub.registry import X`` keeps working.
"""

from ._heartbeat import (
    mark_activity,
    mark_echo_alive,
    set_current_task,
    set_health,
    set_subagent_count,
    set_subagents,
    update_echo_pong,
    update_heartbeat,
    update_pong,
)
from ._payload import get_agents, get_online_count
from ._register import (
    clear_connection_identity,
    decide_singleton_winner,
    get_connection_identity,
    get_recent_singleton_event,
    list_sibling_channels,
    purge_agent,
    purge_all_offline,
    record_singleton_conflict,
    register_agent,
    register_connection,
    set_connection_identity,
    unregister_agent,
    unregister_connection,
)
from ._store import (
    HEARTBEAT_TIMEOUT_S,
    SINGLETON_EVENT_WINDOW_S,
    STALE_PURGE_S,
    _active_session_count,
    _agents,
    _cleanup_locked,
    _connection_identity,
    _connections,
    _lock,
    _singleton_events,
    active_session_count,
    log,
)

__all__ = [
    # Storage primitives (also imported by tests + a few views directly)
    "_agents",
    "_connections",
    "_connection_identity",
    "_singleton_events",
    "_lock",
    "_active_session_count",
    "_cleanup_locked",
    "active_session_count",
    "log",
    "HEARTBEAT_TIMEOUT_S",
    "STALE_PURGE_S",
    "SINGLETON_EVENT_WINDOW_S",
    # Registration / connection lifecycle
    "register_agent",
    "unregister_agent",
    "register_connection",
    "unregister_connection",
    "purge_agent",
    "purge_all_offline",
    # Singleton cardinality enforcement (#255)
    "set_connection_identity",
    "clear_connection_identity",
    "get_connection_identity",
    "list_sibling_channels",
    "decide_singleton_winner",
    "record_singleton_conflict",
    "get_recent_singleton_event",
    # Heartbeat / activity / health setters
    "update_heartbeat",
    "update_pong",
    "update_echo_pong",
    "mark_activity",
    "mark_echo_alive",
    "set_current_task",
    "set_subagents",
    "set_subagent_count",
    "set_health",
    # Dashboard payload assembly
    "get_agents",
    "get_online_count",
]
