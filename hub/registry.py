"""In-memory agent registry -- tracks connected agents and their metadata.

AgentConsumer writes to this registry on register/heartbeat/disconnect.
The REST API reads from it for /api/agents and /api/stats.
"""

import logging
import threading
import time

log = logging.getLogger("orochi.registry")

_lock = threading.Lock()
_agents: dict[str, dict] = {}

# Agents with no heartbeat for this many seconds are auto-marked offline
HEARTBEAT_TIMEOUT_S = 60
# Offline agents are purged from registry after this many seconds
STALE_PURGE_S = 300  # 5 minutes


def register_agent(name: str, workspace_id: int, info: dict) -> None:
    """Register or update an agent."""
    with _lock:
        _agents[name] = {
            "name": name,
            "workspace_id": workspace_id,
            "agent_id": info.get("agent_id", name),
            "machine": info.get("machine", ""),
            "role": info.get("role", ""),
            "model": info.get("model", ""),
            "workdir": info.get("workdir", ""),
            "channels": info.get("channels", []),
            "status": "online",
            "registered_at": time.time(),
            "last_heartbeat": time.time(),
            "metrics": {},
        }


def update_heartbeat(name: str, metrics: dict | None = None) -> None:
    """Update heartbeat timestamp and optional metrics."""
    with _lock:
        if name in _agents:
            _agents[name]["last_heartbeat"] = time.time()
            _agents[name]["status"] = "online"
            if metrics:
                _agents[name]["metrics"] = metrics


def unregister_agent(name: str) -> None:
    """Mark agent as offline and record the time it went offline."""
    with _lock:
        if name in _agents:
            _agents[name]["status"] = "offline"
            _agents[name]["offline_since"] = time.time()


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


def get_agents(workspace_id: int | None = None) -> list[dict]:
    """Return list of agents, optionally filtered by workspace.

    Automatically cleans up stale entries on each call.
    """
    with _lock:
        _cleanup_locked()
        agents = list(_agents.values())
    if workspace_id is not None:
        agents = [a for a in agents if a.get("workspace_id") == workspace_id]
    result = []
    for a in agents:
        from datetime import datetime, timezone

        reg_ts = a.get("registered_at")
        hb_ts = a.get("last_heartbeat")
        result.append(
            {
                "name": a["name"],
                "agent_id": a.get("agent_id", a["name"]),
                "machine": a.get("machine", ""),
                "role": a.get("role", ""),
                "model": a.get("model", ""),
                "workdir": a.get("workdir", ""),
                "icon": a.get("icon", ""),
                "icon_emoji": a.get("icon_emoji", ""),
                "icon_text": a.get("icon_text", ""),
                "channels": list(set(a.get("channels", []))),  # deduplicate
                "status": a.get("status", "online"),
                "registered_at": (
                    datetime.fromtimestamp(reg_ts, tz=timezone.utc).isoformat()
                    if reg_ts
                    else None
                ),
                "last_heartbeat": (
                    datetime.fromtimestamp(hb_ts, tz=timezone.utc).isoformat()
                    if hb_ts
                    else None
                ),
                "metrics": a.get("metrics", {}),
                "current_task": "",
            }
        )
    return result


def get_online_count(workspace_id: int | None = None) -> int:
    """Return number of currently online agents."""
    with _lock:
        _cleanup_locked()
        agents = list(_agents.values())
    if workspace_id is not None:
        agents = [a for a in agents if a.get("workspace_id") == workspace_id]
    return sum(1 for a in agents if a.get("status") == "online")


def purge_all_offline() -> int:
    """Remove all offline/stale agents from registry. Returns count purged."""
    with _lock:
        _cleanup_locked()
        to_delete = [n for n, a in _agents.items() if a["status"] == "offline"]
        for name in to_delete:
            del _agents[name]
        return len(to_delete)


def purge_agent(name: str) -> bool:
    """Remove a specific agent from registry. Returns True if found."""
    with _lock:
        if name in _agents:
            del _agents[name]
            return True
        return False
