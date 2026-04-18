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
"""

import logging
import threading
import time

log = logging.getLogger("orochi.registry")

_lock = threading.Lock()
_agents: dict[str, dict] = {}
_connections: dict[str, set[str]] = {}

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
            # todo#55: canonical FQDN reported by the heartbeat via
            # `socket.getfqdn()`. Display-only — the short `machine` field
            # remains the join key for cards/channels. Preserved across
            # heartbeats that omit the field (older clients).
            "hostname_canonical": info.get("hostname_canonical", "")
            or prev.get("hostname_canonical", ""),
            "role": info.get("role", ""),
            "model": info.get("model", ""),
            "multiplexer": info.get("multiplexer", ""),
            "project": info.get("project", ""),
            "workdir": info.get("workdir", ""),
            # Subscriptions are server-authoritative (ChannelMembership).
            # Preserve prev.channels when a heartbeat omits the field so
            # REST pushers (agent_meta.py) don't wipe subscriptions every
            # 30s. A caller that really wants to clear channels must send
            # "channels": [] explicitly.
            "channels": (
                list(info["channels"])
                if isinstance(info.get("channels"), (list, tuple))
                else prev.get("channels") or []
            ),
            "claude_md": info.get("claude_md", "") or prev.get("claude_md", ""),
            "status": "online",
            "registered_at": prev.get("registered_at") or time.time(),
            "last_heartbeat": time.time(),
            "last_action": prev.get("last_action") or time.time(),
            "last_message_preview": prev.get("last_message_preview", ""),
            "current_task": prev.get("current_task", ""),
            "subagent_count": prev.get("subagent_count", 0),
            "subagents": list(prev.get("subagents") or []),
            "health": prev.get("health") or {},
            "metrics": prev.get("metrics") or {},
            # Extended process/runtime metadata pushed by agent_meta.py --push.
            # Optional; absent for legacy WS-only agents.
            "pid": info.get("pid") or prev.get("pid") or 0,
            "ppid": info.get("ppid") or prev.get("ppid") or 0,
            "context_pct": (
                info.get("context_pct")
                if info.get("context_pct") is not None
                else prev.get("context_pct")
            ),
            "skills_loaded": (
                list(info.get("skills_loaded"))
                if isinstance(info.get("skills_loaded"), (list, tuple))
                else prev.get("skills_loaded") or []
            ),
            "started_at": info.get("started_at") or prev.get("started_at") or "",
            "version": info.get("version") or prev.get("version") or "",
            "runtime": info.get("runtime") or prev.get("runtime") or "",
            # v0.11.0 Agents-tab visibility fields. Recent action log
            # + tmux pane tail + workspace CLAUDE.md head + MCP server
            # list. The bun sidecar pushes these on every 30s
            # heartbeat via api_agents_register; the dashboard reads
            # them from get_agents() to render meaningful cards.
            # todo#155.
            "recent_actions": (
                list(info.get("recent_actions"))
                if isinstance(info.get("recent_actions"), (list, tuple))
                else prev.get("recent_actions") or []
            ),
            "pane_tail": info.get("pane_tail") or prev.get("pane_tail") or "",
            "pane_tail_block": info.get("pane_tail_block")
            or prev.get("pane_tail_block")
            or "",
            # todo#47 — full-scrollback pane for the web-terminal viewer.
            # Pushed by agent_meta.py --push when the client is new
            # enough; older clients never populate it and the UI
            # gracefully falls back to the short pane_tail_block.
            "pane_tail_full": info.get("pane_tail_full")
            or prev.get("pane_tail_full")
            or "",
            "claude_md_head": info.get("claude_md_head")
            or prev.get("claude_md_head")
            or "",
            # todo#460: full .mcp.json content for the Agents tab file viewer.
            # agent_meta.py --push (dotfiles PR #71) sends a size-capped,
            # token-redacted copy of the workspace `.mcp.json`. Absent for
            # legacy WS-only agents; falls through to the empty string.
            "mcp_json": info.get("mcp_json") or prev.get("mcp_json") or "",
            # todo#418: agent decision-transparency fields for the Agents tab.
            # `pane_state` is the classifier label (`running` / `waiting` /
            # `y_n_prompt` / `compose_pending_unsent` / `auth_error` / etc.)
            # computed by agent_meta.py --push using the same classifiers
            # fleet-prompt-actuator uses (scitex_agent_container.runtimes.
            # prompts + detect_compose_pending). `stuck_prompt_text` carries
            # the verbatim prompt so ywatanabe / dashboard viewers can see
            # what the agent is blocked on. Both empty when agent_meta can't
            # classify or the agent is a legacy WS-only pusher.
            "pane_state": info.get("pane_state") or prev.get("pane_state") or "",
            "stuck_prompt_text": info.get("stuck_prompt_text")
            or prev.get("stuck_prompt_text")
            or "",
            "pane_text": info.get("pane_text") or prev.get("pane_text") or "",
            # scitex-agent-container hook-captured tool/prompt events.
            # Lists replace-on-present so a fresh heartbeat always reflects
            # the agent's latest ring-buffer state; empty-list pushes wipe
            # stale data rather than sticking around forever.
            "recent_tools": (
                list(info.get("recent_tools"))
                if isinstance(info.get("recent_tools"), (list, tuple))
                else prev.get("recent_tools") or []
            ),
            "recent_prompts": (
                list(info.get("recent_prompts"))
                if isinstance(info.get("recent_prompts"), (list, tuple))
                else prev.get("recent_prompts") or []
            ),
            "agent_calls": (
                list(info.get("agent_calls"))
                if isinstance(info.get("agent_calls"), (list, tuple))
                else prev.get("agent_calls") or []
            ),
            "background_tasks": (
                list(info.get("background_tasks"))
                if isinstance(info.get("background_tasks"), (list, tuple))
                else prev.get("background_tasks") or []
            ),
            "tool_counts": (
                dict(info.get("tool_counts"))
                if isinstance(info.get("tool_counts"), dict)
                else prev.get("tool_counts") or {}
            ),
            # Functional-heartbeat shortcuts derived in agent-container's
            # event_log.summarize(). last_tool_at is the newest pretool
            # ts (LLM-level liveness); last_mcp_tool_at is newest for
            # mcp__* tools (proves the MCP sidecar route works).
            "last_tool_at": info.get("last_tool_at") or prev.get("last_tool_at") or "",
            "last_tool_name": info.get("last_tool_name")
            or prev.get("last_tool_name")
            or "",
            "last_mcp_tool_at": info.get("last_mcp_tool_at")
            or prev.get("last_mcp_tool_at")
            or "",
            "last_mcp_tool_name": info.get("last_mcp_tool_name")
            or prev.get("last_mcp_tool_name")
            or "",
            # PaneAction summary from scitex-agent-container action_store.
            # Per-push replace semantics (no merge) — a fresh heartbeat
            # always reflects the current log state.
            "last_action_at": info.get("last_action_at")
            or prev.get("last_action_at")
            or "",
            "last_action_name": info.get("last_action_name")
            or prev.get("last_action_name")
            or "",
            "last_action_outcome": info.get("last_action_outcome")
            or prev.get("last_action_outcome")
            or "",
            "last_action_elapsed_s": (
                info.get("last_action_elapsed_s")
                if info.get("last_action_elapsed_s") is not None
                else prev.get("last_action_elapsed_s")
            ),
            "action_counts": (
                dict(info.get("action_counts"))
                if isinstance(info.get("action_counts"), dict)
                else prev.get("action_counts") or {}
            ),
            "p95_elapsed_s_by_action": (
                dict(info.get("p95_elapsed_s_by_action"))
                if isinstance(info.get("p95_elapsed_s_by_action"), dict)
                else prev.get("p95_elapsed_s_by_action") or {}
            ),
            # UI-aligned quota keys (long names).
            "quota_5h_used_pct": (
                info.get("quota_5h_used_pct")
                if info.get("quota_5h_used_pct") is not None
                else prev.get("quota_5h_used_pct")
            ),
            "quota_7d_used_pct": (
                info.get("quota_7d_used_pct")
                if info.get("quota_7d_used_pct") is not None
                else prev.get("quota_7d_used_pct")
            ),
            "quota_5h_reset_at": info.get("quota_5h_reset_at")
            or prev.get("quota_5h_reset_at")
            or "",
            "quota_7d_reset_at": info.get("quota_7d_reset_at")
            or prev.get("quota_7d_reset_at")
            or "",
            "mcp_servers": (
                list(info.get("mcp_servers"))
                if isinstance(info.get("mcp_servers"), (list, tuple))
                else prev.get("mcp_servers") or []
            ),
            # todo#265: Claude Code OAuth account public metadata pushed
            # by agent_meta.py --push so the Agents/Activity tab can show
            # which account each agent is running under, detect
            # out_of_credits state, and support fleet load-balancing.
            # Strict whitelist — no tokens, secrets, or credentials.
            "oauth_email": info.get("oauth_email") or prev.get("oauth_email") or "",
            "oauth_org_name": info.get("oauth_org_name")
            or prev.get("oauth_org_name")
            or "",
            "oauth_account_uuid": info.get("oauth_account_uuid")
            or prev.get("oauth_account_uuid")
            or "",
            "oauth_display_name": info.get("oauth_display_name")
            or prev.get("oauth_display_name")
            or "",
            "billing_type": info.get("billing_type") or prev.get("billing_type") or "",
            "has_available_subscription": (
                info.get("has_available_subscription")
                if info.get("has_available_subscription") is not None
                else prev.get("has_available_subscription")
            ),
            "usage_disabled_reason": info.get("usage_disabled_reason")
            or prev.get("usage_disabled_reason")
            or "",
            "has_extra_usage_enabled": (
                info.get("has_extra_usage_enabled")
                if info.get("has_extra_usage_enabled") is not None
                else prev.get("has_extra_usage_enabled")
            ),
            "subscription_created_at": info.get("subscription_created_at")
            or prev.get("subscription_created_at")
            or "",
            # scitex-orochi#144 fix path 4: how many WebSocket sessions are
            # currently authenticated under this agent name. > 1 indicates
            # a concurrent-instance race situation worth surfacing in the
            # dashboard. The set of connection IDs is held separately in
            # ``_connections`` and counted on read.
            "active_sessions": _active_session_count(name),
            # Quota telemetry from statusline parsing
            "quota_5h_pct": (
                info.get("quota_5h_pct")
                if info.get("quota_5h_pct") is not None
                else prev.get("quota_5h_pct")
            ),
            "quota_5h_remaining": info.get("quota_5h_remaining")
            or prev.get("quota_5h_remaining")
            or "",
            "quota_weekly_pct": (
                info.get("quota_weekly_pct")
                if info.get("quota_weekly_pct") is not None
                else prev.get("quota_weekly_pct")
            ),
            "quota_weekly_remaining": info.get("quota_weekly_remaining")
            or prev.get("quota_weekly_remaining")
            or "",
            "statusline_model": info.get("statusline_model")
            or prev.get("statusline_model")
            or "",
            "account_email": info.get("account_email")
            or prev.get("account_email")
            or "",
        }


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


def register_connection(name: str, conn_id: str) -> int:
    """Track a new WebSocket connection for ``name``.

    Returns the resulting active-session count (i.e. how many connections
    this agent now has, including the one just registered). The caller
    can use this to detect concurrent-instance race situations
    (scitex-orochi#144 fix path 4) and emit visibility warnings when
    the count is > 1.

    Connections are stored as opaque IDs in a per-agent set; passing the
    same ``conn_id`` twice is a no-op (idempotent).
    """
    if not name or not conn_id:
        return 0
    with _lock:
        conns = _connections.setdefault(name, set())
        conns.add(conn_id)
        return len(conns)


def unregister_connection(name: str, conn_id: str) -> int:
    """Remove a WebSocket connection for ``name``.

    Returns the resulting active-session count after removal. When the
    count reaches zero, the agent is marked offline (caller need not
    invoke ``unregister_agent`` separately). When the count is still
    >0 (a sibling session is still alive), the agent remains online.

    This is the fix for the symmetric half of scitex-orochi#144: before
    this change, the first-to-disconnect of N sibling sessions would
    mark the agent offline even though other sessions were still alive.
    """
    if not name or not conn_id:
        return _active_session_count(name)
    with _lock:
        conns = _connections.get(name)
        if conns:
            conns.discard(conn_id)
            if not conns:
                _connections.pop(name, None)
        remaining = len(_connections.get(name, ()))
        if remaining == 0 and name in _agents:
            _agents[name]["status"] = "offline"
            _agents[name]["offline_since"] = time.time()
        return remaining


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


def unregister_agent(name: str) -> None:
    """Mark agent as offline and record the time it went offline.

    Compatibility shim: pre-#144, ``AgentConsumer.disconnect()`` called
    this directly. New flow uses ``unregister_connection(name, conn_id)``
    which handles the offline transition only when the LAST connection
    drops. This function preserves the old contract for callers that
    don't have a connection_id (registry pruning, manual marking, etc.).
    """
    with _lock:
        if name in _agents:
            _agents[name]["status"] = "offline"
            _agents[name]["offline_since"] = time.time()
        # Also clear any tracked connections; this is the "force offline"
        # semantic. If the caller meant a single-session disconnect, they
        # should use unregister_connection instead.
        _connections.pop(name, None)


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
        # Refresh active_sessions on read so the count reflects the latest
        # connect/disconnect events, not just the last register call.
        # scitex-orochi#144 fix path 4.
        for n, a in _agents.items():
            a["active_sessions"] = _active_session_count(n)
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
                    "color": getattr(p, "color", "") or "",
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
                # todo#55: FQDN / canonical hostname for display next to
                # the short machine label. Empty string = older client
                # that didn't push this field.
                "hostname_canonical": a.get("hostname_canonical", ""),
                "role": a.get("role", ""),
                "model": a.get("model", ""),
                "multiplexer": a.get("multiplexer", ""),
                "project": a.get("project", ""),
                "workdir": a.get("workdir", ""),
                "icon": icon_image,
                "icon_emoji": icon_emoji,
                "icon_text": icon_text,
                "color": prof.get("color") or a.get("color", ""),
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
                # todo#46 — hub→agent ping RTT. last_pong_ts is what the
                # dashboard checks to decide whether the PN lamp is live.
                "last_pong_ts": (
                    datetime.fromtimestamp(
                        a["last_pong_ts"], tz=timezone.utc
                    ).isoformat()
                    if a.get("last_pong_ts")
                    else None
                ),
                "last_rtt_ms": a.get("last_rtt_ms"),
                "last_action": (
                    datetime.fromtimestamp(action_ts, tz=timezone.utc).isoformat()
                    if action_ts
                    else None
                ),
                "metrics": a.get("metrics", {}),
                # scitex-orochi#144 fix path 4: number of WebSocket
                # sessions currently authenticated under this name.
                # >1 indicates a concurrent-instance race situation.
                "active_sessions": int(a.get("active_sessions", 0) or 0),
                "current_task": a.get("current_task", ""),
                "last_message_preview": a.get("last_message_preview", ""),
                "subagents": list(a.get("subagents", [])),
                "subagent_count": int(
                    a.get("subagent_count") or len(a.get("subagents") or [])
                ),
                "health": a.get("health") or {},
                "claude_md": a.get("claude_md", ""),
                # Extended metadata from agent_meta.py --push (todo#213)
                "pid": a.get("pid") or 0,
                "ppid": a.get("ppid") or 0,
                "context_pct": a.get("context_pct"),
                "skills_loaded": list(a.get("skills_loaded") or []),
                "started_at": a.get("started_at", ""),
                "version": a.get("version", ""),
                "runtime": a.get("runtime", ""),
                # v0.11.0 Agents-tab visibility fields.
                "recent_actions": list(a.get("recent_actions") or []),
                "pane_tail": a.get("pane_tail", ""),
                "pane_tail_block": a.get("pane_tail_block", ""),
                # todo#47 — full scrollback; empty string if the agent
                # hasn't pushed the new field yet.
                "pane_tail_full": a.get("pane_tail_full", ""),
                "claude_md_head": a.get("claude_md_head", ""),
                "mcp_json": a.get("mcp_json", ""),
                "pane_state": a.get("pane_state", ""),
                "stuck_prompt_text": a.get("stuck_prompt_text", ""),
                "pane_text": a.get("pane_text", ""),
                # scitex-agent-container hook-captured events — lists
                # populated by the PreToolUse/PostToolUse hooks.
                "recent_tools": list(a.get("recent_tools") or []),
                "recent_prompts": list(a.get("recent_prompts") or []),
                "agent_calls": list(a.get("agent_calls") or []),
                "background_tasks": list(a.get("background_tasks") or []),
                "tool_counts": dict(a.get("tool_counts") or {}),
                # Functional-heartbeat shortcuts (derived by
                # event_log.summarize() in agent-container).
                "last_tool_at": a.get("last_tool_at", ""),
                "last_tool_name": a.get("last_tool_name", ""),
                "last_mcp_tool_at": a.get("last_mcp_tool_at", ""),
                "last_mcp_tool_name": a.get("last_mcp_tool_name", ""),
                # PaneAction summary (scitex-agent-container action_store).
                # NB: ``last_action_name`` (not ``last_action``) to avoid
                # collision with the pre-existing ``last_action`` field
                # which is the unix-time liveness timestamp set by
                # ``mark_activity``.
                "last_action_at": a.get("last_action_at", ""),
                "last_action_name": a.get("last_action_name", ""),
                "last_action_outcome": a.get("last_action_outcome", ""),
                "last_action_elapsed_s": a.get("last_action_elapsed_s"),
                "action_counts": dict(a.get("action_counts") or {}),
                "p95_elapsed_s_by_action": dict(a.get("p95_elapsed_s_by_action") or {}),
                # UI-aligned quota keys — long-name variants surfaced so
                # the Agents-tab meta grid sees them under the names it
                # reads.
                "quota_5h_used_pct": a.get("quota_5h_used_pct"),
                "quota_7d_used_pct": a.get("quota_7d_used_pct"),
                "quota_5h_reset_at": a.get("quota_5h_reset_at", ""),
                "quota_7d_reset_at": a.get("quota_7d_reset_at", ""),
                "mcp_servers": list(a.get("mcp_servers") or []),
                # todo#265: OAuth account public metadata. Whitelist
                # only — no tokens, credentials, or secrets are ever
                # stored or surfaced.
                "oauth_email": a.get("oauth_email", ""),
                "oauth_org_name": a.get("oauth_org_name", ""),
                "oauth_account_uuid": a.get("oauth_account_uuid", ""),
                "oauth_display_name": a.get("oauth_display_name", ""),
                "billing_type": a.get("billing_type", ""),
                "has_available_subscription": a.get("has_available_subscription"),
                "usage_disabled_reason": a.get("usage_disabled_reason", ""),
                "has_extra_usage_enabled": a.get("has_extra_usage_enabled"),
                "subscription_created_at": a.get("subscription_created_at", ""),
                # Quota telemetry from statusline parsing (agent_meta.py)
                "quota_5h_pct": a.get("quota_5h_pct"),
                "quota_5h_remaining": a.get("quota_5h_remaining", ""),
                "quota_weekly_pct": a.get("quota_weekly_pct"),
                "quota_weekly_remaining": a.get("quota_weekly_remaining", ""),
                "statusline_model": a.get("statusline_model", ""),
                "account_email": a.get("account_email", ""),
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
