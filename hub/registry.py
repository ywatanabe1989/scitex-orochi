"""In-memory agent registry -- tracks connected agents and their metadata.

AgentConsumer writes to this registry on register/heartbeat/disconnect.
The REST API reads from it for /api/agents and /api/stats.
"""

import threading
import time

_lock = threading.Lock()
_agents: dict[str, dict] = {}


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
            if metrics:
                _agents[name]["metrics"] = metrics


def unregister_agent(name: str) -> None:
    """Mark agent as offline (don't delete -- keep metadata for display)."""
    with _lock:
        if name in _agents:
            _agents[name]["status"] = "offline"


def get_agents(workspace_id: int | None = None) -> list[dict]:
    """Return list of agents, optionally filtered by workspace."""
    with _lock:
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
        agents = list(_agents.values())
    if workspace_id is not None:
        agents = [a for a in agents if a.get("workspace_id") == workspace_id]
    return sum(1 for a in agents if a.get("status") == "online")
