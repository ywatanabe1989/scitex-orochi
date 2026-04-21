"""Heartbeat / activity / health setters for the in-memory registry.

These mutate per-agent state populated by the WS consumer or REST
pushers (heartbeat tick, ping/pong RTT, classifier-supplied health,
explicit task / subagent updates from agents).
"""

import time

from ._store import _agents, _lock


def set_subagents(name: str, subagents: list) -> None:
    """Replace the agent's subagent list.

    Each subagent entry is a dict with at least {name, task} and optionally
    {status}. Caller is expected to send the full current list — this is a
    full replacement, not an append.
    """
    with _lock:
        if name in _agents:
            normalized = [
                {
                    "name": str(s.get("name", "")) or "subagent",
                    "task": str(s.get("task", ""))[:200],
                    "status": str(s.get("status", "running")),
                }
                for s in (subagents or [])
                if isinstance(s, dict)
            ]
            _agents[name]["subagents"] = normalized
            # Keep the count in sync so callers that only read
            # `subagent_count` (sidebar card badge) stay accurate even
            # when the full list is what was pushed.
            _agents[name]["subagent_count"] = len(normalized)


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


def set_subagent_count(name: str, count: int) -> None:
    """Explicitly set the agent's subagent count.

    Agents that track subagents out-of-band (without sending the full
    subagents list) can report just the count via this setter so the
    dashboard can still show a `N subagents` badge.
    """
    with _lock:
        if name in _agents:
            _agents[name]["subagent_count"] = max(0, int(count or 0))


def set_health(
    name: str, status: str, reason: str = "", source: str = "caduceus"
) -> None:
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


def update_pong(name: str, rtt_ms: float) -> None:
    """Record a hub→agent pong's RTT so the PN lamp goes live (todo#46).

    Stores both the RTT and the pong timestamp — the dashboard treats
    a stale ``last_pong_ts`` as "no recent pong" independent of the RTT
    value, so an agent that stops responding is visibly degraded.
    """
    with _lock:
        if name in _agents:
            _agents[name]["last_pong_ts"] = time.time()
            _agents[name]["last_rtt_ms"] = float(rtt_ms)


def update_echo_pong(name: str, rtt_ms: float) -> None:
    """Record an agent's echo round-trip pong (#259, indicator #4).

    Sets three fields:

    - ``last_echo_rtt_ms`` — most recent echo RTT in milliseconds.
    - ``last_echo_ok_ts``  — wall time of the most recent successful
      echo (unix seconds, float). Used by the API/payload layer.
    - ``last_nonce_echo_at`` — ISO-8601 string of the same instant,
      consumed directly by the Agents-tab LED renderer
      (``renderAgentLeds`` reads ``a.last_nonce_echo_at``).

    All three are written atomically so a partial update can't leave
    the LED rendering off a fresher timestamp than the RTT it cites.
    """
    from datetime import datetime, timezone

    now = time.time()
    iso_now = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
    with _lock:
        if name in _agents:
            _agents[name]["last_echo_rtt_ms"] = float(rtt_ms)
            _agents[name]["last_echo_ok_ts"] = now
            _agents[name]["last_nonce_echo_at"] = iso_now
