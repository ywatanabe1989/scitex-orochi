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
            # `orochi_subagent_count` (sidebar card badge) stay accurate even
            # when the full list is what was pushed.
            _agents[name]["orochi_subagent_count"] = len(normalized)


def mark_activity(name: str, action: str = "") -> None:
    """Record that an agent did something meaningful (sent a message, ran a tool).

    The `action` argument is stored as `last_message_preview` (a truncated
    chat preview shown in the Activity tab). It does NOT overwrite
    `orochi_current_task` — that field is reserved for STRUCTURED task IDs set
    explicitly via `set_orochi_current_task()` (e.g. from a `task_update` WS
    message or `orochi report activity --task ...`). Conflating the two
    leaked chat-preview text into the structured task column.
    """
    with _lock:
        if name in _agents:
            _agents[name]["last_action"] = time.time()
            if action:
                _agents[name]["last_message_preview"] = action[:120]


def set_orochi_current_task(name: str, task: str) -> None:
    """Explicitly set the agent's current task description."""
    with _lock:
        if name in _agents:
            _agents[name]["orochi_current_task"] = task[:120] if task else ""


def set_orochi_subagent_count(name: str, count: int) -> None:
    """Explicitly set the agent's subagent count.

    Agents that track subagents out-of-band (without sending the full
    subagents list) can report just the count via this setter so the
    dashboard can still show a `N subagents` badge.
    """
    with _lock:
        if name in _agents:
            _agents[name]["orochi_subagent_count"] = max(0, int(count or 0))


def set_sac_status(name: str, sac_status: dict) -> None:
    """Store the full ``scitex-agent-container status --terse --json`` dict.

    Lead msg#16005 pivot: the heartbeat pusher shells out to ``sac
    status --terse --json`` and forwards the resulting dict verbatim so
    future additions to sac's terse projection (``orochi_context_pct``,
    ``orochi_pane_state``, ``orochi_current_tool``, quota fields, ...) surface on
    ``/api/agents/`` without per-field plumbing on the hub side.

    Replace-on-present semantics — every heartbeat re-runs sac, so the
    dict is always current. Non-dict / empty pushes are ignored (the
    previous value is preserved) so a transient CLI failure doesn't
    clear the field.
    """
    if not isinstance(sac_status, dict) or not sac_status:
        return
    with _lock:
        if name in _agents:
            _agents[name]["sac_status"] = dict(sac_status)


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
    """Update heartbeat timestamp and optional metrics.

    todo#272: after the timestamp/metric write, run the quota-pressure
    state machine for this agent. The check reads the quota fields that
    ``register_agent()`` just wrote (``quota_5h_used_pct`` / ``quota_7d_used_pct``
    + reset timestamps + prior state) and posts a threshold-crossing
    message to ``#progress`` / ``#escalation`` / ``#ywatanabe`` when a
    window crosses the warn / escalate bands. Best-effort — the check
    never raises into the heartbeat hot path.

    msg#16388: after quota pressure, run the auto-dispatch state machine
    for ``head-*`` agents. ``check_agent_auto_dispatch()`` reads
    ``orochi_subagent_count`` (just written by the heartbeat handler via
    ``set_orochi_subagent_count``) and maintains a per-head idle streak + 15min
    cooldown, firing a DM when a head stalls for N consecutive zero
    readings. Also best-effort.
    """
    with _lock:
        if name in _agents:
            _agents[name]["last_heartbeat"] = time.time()
            _agents[name]["status"] = "online"
            if metrics:
                # MERGE, not overwrite. Multiple producers contribute to
                # ``metrics`` (collect_machine_metrics → host CPU/mem/disk;
                # collect_orochi_slurm_status → cluster_* aggregates;
                # scitex-agent-container's sac_status → its own subset).
                # A producer that only knows about a subset (e.g. a
                # Slurm-only host producing cluster_* fields) used to wipe
                # the host-level fields a richer producer had written, so
                # the Machines tab card showed dashes for cores/disk even
                # though some producer had populated them.
                # Preserving keys absent from the new push avoids that
                # silent wipe; the producer can still reset a key by
                # sending it with a falsy value (the dashboard renders
                # 0 / empty as the appropriate "n/a"). 2026-04-28.
                prev_metrics = _agents[name].get("metrics") or {}
                merged = dict(prev_metrics)
                # Skip explicit ``None`` values — a producer that
                # doesn't have a metric should OMIT it, not send
                # ``None`` and wipe whatever a richer producer wrote.
                # Falsy non-None values (0, "", []) DO overwrite, so a
                # producer can still reset (e.g. set GPU list to []).
                merged.update({k: v for k, v in metrics.items() if v is not None})
                _agents[name]["metrics"] = merged
            has_agent = True
        else:
            has_agent = False

    if has_agent:
        # Deferred import — avoid circular (``hub.quota_watch`` itself
        # imports ``hub.registry``).
        try:
            from hub.quota_watch import check_agent_quota_pressure

            check_agent_quota_pressure(name)
        except Exception:  # pragma: no cover — defense in depth
            pass

        # msg#16388 Layer 1 redesign — server-side auto-dispatch hook.
        # Only fires for ``head-*`` agents (internal name prefix check).
        # Deferred import to avoid a circular through hub.registry.
        try:
            from hub.auto_dispatch import check_agent_auto_dispatch

            check_agent_auto_dispatch(name)
        except Exception:  # pragma: no cover — defense in depth
            pass


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

    Semantic note (msg#15538 — 4th-LED auto-green on inbound message):
    ``last_nonce_echo_at`` is now the "last proof of life" timestamp,
    written either by this setter (successful nonce probe, carries RTT)
    OR by ``mark_echo_alive()`` (any inbound agent message, no RTT).
    Both paths feed the same LED field so either signal turns it green.
    """
    from datetime import datetime, timezone

    now = time.time()
    iso_now = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
    with _lock:
        if name in _agents:
            _agents[name]["last_echo_rtt_ms"] = float(rtt_ms)
            _agents[name]["last_echo_ok_ts"] = now
            _agents[name]["last_nonce_echo_at"] = iso_now


def mark_echo_alive(name: str) -> None:
    """Record proof-of-life from an inbound agent message (msg#15538).

    The 4th LED (ECHO / ``last_nonce_echo_at``) was previously only
    driven by the hub→agent nonce round-trip in ``_hub_echo_loop`` /
    ``handle_echo_pong``. If the agent's MCP-client could not reply to
    the nonce (e.g. the sidecar was down) the LED stayed amber / red
    even though the agent was clearly alive — we had just received a
    chat message from it.

    This setter is called from ``handle_agent_message`` when a
    ``type: "message"`` frame lands on the WS (after ACL + membership
    checks pass, so only authenticated inbound traffic is credited).
    It advances the same ``last_nonce_echo_at`` / ``last_echo_ok_ts``
    pair the nonce-probe setter writes — the LED renderer needs no
    change; it just sees the hot timestamp regardless of which
    mechanism produced it.

    Does NOT touch ``last_echo_rtt_ms`` — an inbound message has no
    round-trip measurement, and overwriting a real RTT with a sentinel
    would make the per-agent detail panel's RTT display misleading.
    The two mechanisms together are a strictly stronger liveness signal
    than nonce-probe alone (either path turns the LED green).
    """
    from datetime import datetime, timezone

    now = time.time()
    iso_now = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
    with _lock:
        if name in _agents:
            _agents[name]["last_echo_ok_ts"] = now
            _agents[name]["last_nonce_echo_at"] = iso_now
