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
    """Register or update an agent.

    Re-registration (e.g. WS reconnect) preserves narrative state that
    the agent populated via later calls — current_task, last_message,
    subagents. Without this, every WS reconnect wiped the Activity tab
    fields back to empty strings so cards always read "no task reported".
    """
    with _lock:
        prev = _agents.get(name, {}) or {}
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
            "registered_at": prev.get("registered_at") or time.time(),
            "last_heartbeat": time.time(),
            "last_action": prev.get("last_action") or time.time(),
            "last_message_preview": prev.get("last_message_preview", ""),
            "current_task": prev.get("current_task", ""),
            "subagents": list(prev.get("subagents") or []),
            "health": prev.get("health") or {},
            "metrics": prev.get("metrics") or {},
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


def set_health(name: str, status: str, reason: str = "", source: str = "caduceus") -> None:
    """Record caduceus's (or any healer's) diagnosis for an agent.

    status — free-form string (mamba taxonomy — healthy, idle, stale,
    stuck_prompt, dead, ghost, degraded, remediating, unknown, ...)
    reason — short free-text explanation (<= 200 chars)
    source — who wrote this diagnosis (default caduceus)

    Writes to the in-memory registry AND persists to AgentProfile so
    the diagnosis survives container restarts. Without persistence,
    caduceus has to re-POST after every deploy.
    """
    import time as _time
    st = (status or "unknown")[:32]
    rn = (reason or "")[:200]
    sc = (source or "")[:64]
    with _lock:
        if name in _agents:
            _agents[name]["health"] = {
                "status": st,
                "reason": rn,
                "source": sc,
                "ts": _time.time(),
            }
            workspace_id = _agents[name].get("workspace_id")
        else:
            workspace_id = None

    # Best-effort persist to AgentProfile. Swallow errors so health
    # updates never break the hot path.
    if workspace_id is not None:
        try:
            from django.utils import timezone
            from hub.models import AgentProfile

            AgentProfile.objects.update_or_create(
                workspace_id=workspace_id,
                name=name,
                defaults={
                    "health_status": st,
                    "health_reason": rn,
                    "health_source": sc,
                    "health_ts": timezone.now(),
                },
            )
        except Exception:
            pass


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
    Merges persistent per-agent display profiles (AgentProfile) over
    the in-memory transient icon fields so user-configured icons
    survive across agent restarts.
    """
    with _lock:
        _cleanup_locked()
        agents = list(_agents.values())
    if workspace_id is not None:
        agents = [a for a in agents if a.get("workspace_id") == workspace_id]

    # Load persistent profiles once per call and build a lookup.
    profile_by_name: dict[str, dict] = {}
    if workspace_id is not None:
        try:
            from hub.models import AgentProfile

            for p in AgentProfile.objects.filter(workspace_id=workspace_id):
                profile_by_name[p.name] = {
                    "icon_emoji": p.icon_emoji or "",
                    "icon_image": p.icon_image or "",
                    "icon_text": p.icon_text or "",
                    "health_status": p.health_status or "",
                    "health_reason": p.health_reason or "",
                    "health_source": p.health_source or "",
                    "health_ts": p.health_ts,
                }
        except Exception:
            pass

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
        # Prefer persistent profile icon over transient register-time icon
        prof = profile_by_name.get(a["name"], {})
        icon_image = prof.get("icon_image") or a.get("icon", "")
        icon_emoji = prof.get("icon_emoji") or a.get("icon_emoji", "")
        icon_text = prof.get("icon_text") or a.get("icon_text", "")
        # Health: in-memory wins when present (fresh updates from current
        # session), fall back to the persisted profile row so the pill
        # survives container restarts. Timestamps converted to ISO.
        live_health = a.get("health") or {}
        health = live_health
        if not live_health and prof.get("health_status"):
            _ts = prof.get("health_ts")
            health = {
                "status": prof.get("health_status") or "",
                "reason": prof.get("health_reason") or "",
                "source": prof.get("health_source") or "",
                "ts": _ts.isoformat() if _ts else None,
            }
        result.append(
            {
                "name": a["name"],
                "agent_id": a.get("agent_id", a["name"]),
                "machine": a.get("machine", ""),
                "role": a.get("role", ""),
                "model": a.get("model", ""),
                "workdir": a.get("workdir", ""),
                "icon": icon_image,
                "icon_emoji": icon_emoji,
                "icon_text": icon_text,
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
                "health": a.get("health") or {},
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
