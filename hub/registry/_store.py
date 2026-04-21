"""Storage primitives for the in-memory agent registry.

Holds the process-local ``_agents`` and ``_connections`` dicts, the
shared ``_lock``, low-level session-count helpers, and the stale-entry
``_cleanup_locked`` routine.

These primitives are imported by the higher-level register / heartbeat
/ payload modules and by a handful of tests/views that read the dicts
directly. The names are part of the registry's public surface.
"""

import logging
import threading
import time
from collections import deque

log = logging.getLogger("orochi.registry")

_lock = threading.Lock()
_agents: dict[str, dict] = {}
_connections: dict[str, set[str]] = {}
# scitex-orochi#255 — per-channel connection identity for singleton
# enforcement. Maps channel_name -> {"agent": str, "instance_id": str,
# "start_ts_unix": float | None}. Populated by ``set_connection_identity``
# at register-frame time so the hub can decide singleton conflicts even
# after the second WS connection has already accepted (the register frame
# is what carries the per-process identity).
_connection_identity: dict[str, dict] = {}
# scitex-orochi#255 — bounded ring buffer of singleton-conflict events.
# Each entry: {"name": agent_name, "ts": float, "winner_instance_id":
# str, "loser_instance_id": str, "winner_start_ts_unix": float | None,
# "loser_start_ts_unix": float | None, "outcome": "incumbent" | "challenger"}.
# Newest events appended on the right; we cap the buffer so a runaway
# crash loop can't OOM the hub. The detail API filters by ``ts`` >=
# now-3600 so an event ages out of the dashboard banner one hour after
# it occurred even if it's still in the buffer.
SINGLETON_EVENTS_MAX = 256
SINGLETON_EVENT_WINDOW_S = 3600  # 1 hour
_singleton_events: deque[dict] = deque(maxlen=SINGLETON_EVENTS_MAX)

# Agents with no heartbeat for this many seconds are auto-marked offline
HEARTBEAT_TIMEOUT_S = 60
# Offline agents are purged from registry after this many seconds
STALE_PURGE_S = 300  # 5 minutes


def _active_session_count(name: str) -> int:
    """Return the active-session count for ``name`` without acquiring the lock.

    Caller must hold ``_lock`` if reading inside another locked region;
    used internally + by ``get_agents()``.
    """
    return len(_connections.get(name, ()))


def active_session_count(name: str) -> int:
    """Public read of the active-session count for ``name`` (lock-acquiring)."""
    with _lock:
        return _active_session_count(name)


def _cleanup_locked() -> None:
    """Expire stale agents. Must be called while holding _lock."""
    now = time.time()
    to_delete = []
    for name, a in _agents.items():
        # Auto-mark online agents as offline if heartbeat is stale
        if a["status"] == "online":
            elapsed = now - a.get("last_heartbeat", 0)
            if elapsed > HEARTBEAT_TIMEOUT_S:
                a["status"] = "offline"
                a.setdefault("offline_since", now)
                log.info(
                    "Agent %s auto-marked offline (no heartbeat for %ds)",
                    name,
                    int(elapsed),
                )
        # Purge offline agents after STALE_PURGE_S
        if a["status"] == "offline":
            offline_since = a.get("offline_since", a.get("last_heartbeat", 0))
            if now - offline_since > STALE_PURGE_S:
                to_delete.append(name)
    for name in to_delete:
        log.info("Purging stale agent %s from registry", name)
        del _agents[name]
