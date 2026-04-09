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
            "last_action": time.time(),  # last meaningful activity (msg, tool call)
            "last_message_preview": "",  # truncated last chat message text
            "current_task": "",  # structured task ID/desc; only set explicitly
            "subagents": [],  # list[dict]: {name, task, status} reported by parent
            "metrics": {},
        }


def set_subagents(name: str, subagents: list) -> None:
    """Replace the agent's subagent list.

    Each subagent entry is a dict with at least {name, task} and optionally
    {status}. Caller is expected to send the full current list — this is a
    full replacement, not an append.
    """
    with _lock:
        if name in _agents:
            _agents[name]["subagents"] = [
                {
                    "name": str(s.get("name", "")) or "subagent",
                    "task": str(s.get("task", ""))[:200],
                    "status": str(s.get("status", "running")),
                }
                for s in (subagents or [])
                if isinstance(s, dict)
            ]


def mark_activity(name: str, action: str = "") -> None:
    """Record that an agent did something meaningful (sent a message, ran a tool).

    The `action` argument is stored as `last_message_preview` (a truncated
    chat preview shown in the Activity tab). It does NOT overwrite
    `current_task` — that field is reserved for STRUCTURED task IDs set
    explicitly via `set_current_task()` (e.g. from a `task_update` WS
    message or `orochi report activity --task ...`). Conflating the two
    leaked chat-preview text into the structured task column.
    """
    with _lock:
        if name in _agents:
            _agents[name]["last_action"] = time.time()
            if action:
                _agents[name]["last_message_preview"] = action[:120]


def set_current_task(name: str, task: str) -> None:
    """Explicitly set the agent's current task description."""
    with _lock:
        if name in _agents:
            _agents[name]["current_task"] = task[:120] if task else ""


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
    now = time.time()
    for a in agents:
        from datetime import datetime, timezone

        reg_ts = a.get("registered_at")
        hb_ts = a.get("last_heartbeat")
        action_ts = a.get("last_action")
        # Liveness classification distinct from WS connection state.
        # An agent can be "online" (WS open) but "stale" (no activity for >2min).
        liveness = a.get("status", "online")
        idle_seconds = None
        if action_ts:
            idle_seconds = int(now - action_ts)
            if a.get("status") == "online":
                if idle_seconds > 600:
                    liveness = "stale"  # >10min silent — probably stuck
                elif idle_seconds > 120:
                    liveness = "idle"  # >2min silent — paused/thinking
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
                "liveness": liveness,
                "idle_seconds": idle_seconds,
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
                "last_action": (
                    datetime.fromtimestamp(action_ts, tz=timezone.utc).isoformat()
                    if action_ts
                    else None
                ),
                "metrics": a.get("metrics", {}),
                "current_task": a.get("current_task", ""),
                "last_message_preview": a.get("last_message_preview", ""),
                "subagents": list(a.get("subagents", [])),
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
