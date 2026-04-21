"""Agent + connection (un)registration.

``register_agent`` carries the prev-preserve field list — every per-agent
field that must survive a re-register (heartbeat / WS reconnect) without
flickering. New per-agent fields MUST be added here, otherwise the LEDs
flicker every heartbeat (regression hazard).
"""

import time

from ._store import (
    SINGLETON_EVENT_WINDOW_S,
    _active_session_count,
    _agents,
    _connection_identity,
    _connections,
    _lock,
    _singleton_events,
    log,
)


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
            # ── #257 canonical heartbeat metadata ─────────────────────
            # `hostname` is what `hostname(1)` returns on the running
            # process — single source of truth for "where am I", per
            # ywatanabe msg #14726/#14730: never display a fabricated or
            # cached @host label. Distinct from `machine` (YAML config
            # label) and `hostname_canonical` (FQDN via getfqdn()).
            # If the heartbeat omits it, fall through to the previous
            # value rather than wiping — older clients that haven't
            # been upgraded yet keep working.
            "hostname": info.get("hostname", "") or prev.get("hostname", ""),
            # `uname -a` output. Lets the dashboard surface kernel /
            # arch info in the agent detail pane (HANDOFF.md #1 spec).
            "uname": info.get("uname", "") or prev.get("uname", ""),
            # Process start time as unix epoch (float). Distinct from
            # `started_at` (ISO string) — the unix form is the
            # authoritative tiebreaker for singleton enforcement
            # (HANDOFF #255: oldest start_ts wins when two processes
            # claim the same name). Preserved across re-registers so
            # the WS reconnect doesn't reset the clock.
            "start_ts_unix": (
                info.get("start_ts_unix")
                if info.get("start_ts_unix") is not None
                else prev.get("start_ts_unix")
            ),
            # Per-process UUID generated once at agent boot. Lets the
            # hub distinguish two processes claiming the same agent
            # name (the ghost-mba bug from #256). Preserved — a new
            # instance_id from a heartbeat means a different process
            # took over (or a fast restart happened).
            "instance_id": info.get("instance_id", "")
            or prev.get("instance_id", ""),
            # Whether this instance considers itself a non-primary
            # proxy (rank > 0 in its YAML priority list). True means
            # the agent should be silent in public channels per
            # HANDOFF §2 rule #2 (non-primary silence). Kept as bool
            # — older clients that don't report it default to False
            # so they keep posting normally.
            "is_proxy": bool(info.get("is_proxy"))
            if info.get("is_proxy") is not None
            else bool(prev.get("is_proxy")),
            # 0-based index in the YAML `host:` priority list (0 =
            # primary). Lets the dashboard sort multiple instances of
            # the same agent by priority and lets the hub pick the
            # winner when two connect simultaneously.
            "priority_rank": (
                info.get("priority_rank")
                if info.get("priority_rank") is not None
                else prev.get("priority_rank")
            ),
            # Full priority list from YAML — useful for the Agents
            # tab detail pane to show "would prefer to run on X / Y /
            # Z but currently on N". List of hostnames.
            "priority_list": (
                list(info["priority_list"])
                if isinstance(info.get("priority_list"), (list, tuple))
                else (prev.get("priority_list") or [])
            ),
            # How the agent process was started: sac | sac-ssh |
            # sbatch | manual-tmux | manual-direct | unknown. The
            # launcher sets SCITEX_AGENT_LAUNCH_METHOD env var; the
            # agent reads it once at boot and reports here. Lets a
            # human glance at the dashboard and know how to restart.
            "launch_method": info.get("launch_method", "")
            or prev.get("launch_method", ""),
            # Monotonically incrementing heartbeat sequence number per
            # process. Reset to 0 on each new instance_id. Lets the
            # hub detect missed heartbeats / clock skew without
            # comparing wall times.
            "heartbeat_seq": (
                info.get("heartbeat_seq")
                if info.get("heartbeat_seq") is not None
                else prev.get("heartbeat_seq", 0)
            ),
            # ── /#257 ─────────────────────────────────────────────────
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
            # todo#46 — preserve ping/pong state across re-registers
            # (heartbeat, WS reconnect). Without this, every heartbeat
            # wiped last_pong_ts/last_rtt_ms back to absent, so the RT
            # lamp flickered to gray 1× per 30s heartbeat cycle.
            "last_pong_ts": prev.get("last_pong_ts"),
            "last_rtt_ms": prev.get("last_rtt_ms"),
            # #259 — preserve echo round-trip state across re-registers.
            # The 4th LED (Remote / nonce echo) renders from
            # `last_nonce_echo_at` (ISO string consumed by
            # renderAgentLeds). Without prev-preserve, the LED would
            # flicker grey on every heartbeat cycle (same pitfall as
            # last_pong_ts). update_echo_pong is the canonical setter.
            "last_echo_rtt_ms": prev.get("last_echo_rtt_ms"),
            "last_echo_ok_ts": prev.get("last_echo_ok_ts"),
            "last_nonce_echo_at": prev.get("last_nonce_echo_at"),
            # Extended process/runtime metadata pushed by agent_meta.py --push.
            # Optional; absent for legacy WS-only agents.
            "pid": info.get("pid") or prev.get("pid") or 0,
            "ppid": info.get("ppid") or prev.get("ppid") or 0,
            "context_pct": (
                info.get("context_pct")
                if info.get("context_pct") is not None
                else prev.get("context_pct")
            ),
            # YAML compact policy block from sac status. Preserve across
            # heartbeats so the Agents tab keeps showing the threshold even
            # when an individual heartbeat omits it (legacy clients).
            "context_management": (
                info.get("context_management")
                if info.get("context_management") is not None
                else prev.get("context_management")
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


def purge_all_offline() -> int:
    """Remove all offline/stale agents from registry. Returns count purged."""
    from ._store import _cleanup_locked

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


# ── scitex-orochi#255 — singleton cardinality enforcement ────────────
#
# The two-process race that motivated #255: when sac (or a human) starts
# a second copy of an agent that already has a live WS, both processes
# claim the same ``SCITEX_OROCHI_AGENT`` identity. Pre-#255 behaviour
# admitted both — they then fought for the heartbeat slot, the dashboard
# flickered between their states, and DM routing was racy. Post-#255 the
# hub picks one winner and closes the loser with WebSocket close code
# 4409 / reason ``duplicate_identity`` so the loser exits cleanly.
#
# Decision rule (HANDOFF.md §3 #3 + ywatanabe msg #14757):
#
#   1. Need *both* sides to report ``instance_id`` AND ``start_ts_unix``
#      to enforce — legacy clients that report neither fall through to
#      the permissive "allow both" behaviour with a logged WARNING (no
#      regression for older agent_meta.py installs).
#   2. Same ``instance_id``: not a conflict — same process re-registering
#      after a transient WS reconnect. Treat as incumbent-wins (no-op).
#   3. Different ``instance_id`` AND both have ``start_ts_unix``: the
#      OLDER ``start_ts_unix`` wins. Original process keeps its claim.
#   4. Tie (equal ``start_ts_unix``) or one side missing the field:
#      incumbent wins (don't disrupt the running process).


def set_connection_identity(
    channel_name: str,
    agent_name: str,
    instance_id: str | None,
    start_ts_unix: float | None,
) -> None:
    """Remember the per-process identity behind ``channel_name``.

    Called from the register-frame handler so that when a *future* second
    register frame arrives under the same ``agent_name`` we can compare
    its ``(instance_id, start_ts_unix)`` against every currently-live
    sibling channel and decide who survives.

    Lookup direction is channel→identity (not name→identity) because
    ``_agents[name]`` only ever stores ONE process's identity at a time;
    the per-channel map is what lets us close the right WebSocket when
    the challenger wins.
    """
    if not channel_name or not agent_name:
        return
    with _lock:
        _connection_identity[channel_name] = {
            "agent": agent_name,
            "instance_id": instance_id or "",
            "start_ts_unix": (
                float(start_ts_unix) if start_ts_unix is not None else None
            ),
        }


def clear_connection_identity(channel_name: str) -> None:
    """Forget per-channel identity on disconnect.

    Mirrors ``unregister_connection`` so the per-channel map doesn't grow
    monotonically over the hub's lifetime.
    """
    if not channel_name:
        return
    with _lock:
        _connection_identity.pop(channel_name, None)


def get_connection_identity(channel_name: str) -> dict | None:
    """Return the per-channel identity dict, or ``None`` if not tracked."""
    with _lock:
        if channel_name in _connection_identity:
            return dict(_connection_identity[channel_name])
        return None


def list_sibling_channels(agent_name: str, exclude: str = "") -> list[dict]:
    """Return identity dicts for every other live channel claiming ``agent_name``.

    Used by the register handler to find candidates to compare the new
    challenger against. ``exclude`` is the new connection's own channel
    name so we don't compare it with itself.
    """
    if not agent_name:
        return []
    with _lock:
        return [
            {"channel_name": ch, **ident}
            for ch, ident in _connection_identity.items()
            if ident.get("agent") == agent_name and ch != exclude
        ]


def decide_singleton_winner(
    incumbent_instance_id: str | None,
    incumbent_start_ts_unix: float | None,
    challenger_instance_id: str | None,
    challenger_start_ts_unix: float | None,
) -> str:
    """Pick the winner of a two-process singleton race.

    Returns ``"incumbent"`` when the existing connection should keep the
    claim and the challenger should be closed; ``"challenger"`` when the
    new connection wins and the incumbent should be evicted.

    Rule precedence (matches the module-level docstring):

      1. If either side is missing ``instance_id`` -> incumbent wins
         (legacy permissive mode). The caller is expected to log a
         WARNING in that branch so the situation is still observable.
      2. Same ``instance_id`` -> incumbent (treat as harmless re-register,
         not a real conflict — the caller decides not to close anyone).
      3. Both have ``start_ts_unix`` and they differ -> older
         ``start_ts_unix`` wins.
      4. Tie or one side missing ``start_ts_unix`` -> incumbent wins
         (don't disrupt the running process).
    """
    # Rule 1 — legacy permissive mode. Either side can't enforce.
    if not incumbent_instance_id or not challenger_instance_id:
        return "incumbent"
    # Rule 2 — same process re-registering, not a conflict.
    if incumbent_instance_id == challenger_instance_id:
        return "incumbent"
    # Rule 3 — strict tiebreaker on start_ts_unix.
    if (
        incumbent_start_ts_unix is not None
        and challenger_start_ts_unix is not None
        and incumbent_start_ts_unix != challenger_start_ts_unix
    ):
        return (
            "incumbent"
            if incumbent_start_ts_unix < challenger_start_ts_unix
            else "challenger"
        )
    # Rule 4 — tie or missing tiebreaker; protect the running process.
    return "incumbent"


def record_singleton_conflict(
    name: str,
    winner_instance_id: str,
    loser_instance_id: str,
    winner_start_ts_unix: float | None = None,
    loser_start_ts_unix: float | None = None,
    outcome: str = "incumbent",
) -> dict:
    """Append a singleton-conflict event to the bounded ring buffer.

    The dashboard reads back the most recent event per agent via
    ``get_recent_singleton_event(name)`` and surfaces a banner /
    detail-pane warning when the event is within the last hour.

    ``outcome`` is the verbatim return value of ``decide_singleton_winner``
    so the dashboard / log reader can tell which side actually got
    closed without re-running the rule.
    """
    event = {
        "name": name,
        "ts": time.time(),
        "winner_instance_id": winner_instance_id or "",
        "loser_instance_id": loser_instance_id or "",
        "winner_start_ts_unix": (
            float(winner_start_ts_unix)
            if winner_start_ts_unix is not None
            else None
        ),
        "loser_start_ts_unix": (
            float(loser_start_ts_unix)
            if loser_start_ts_unix is not None
            else None
        ),
        "outcome": outcome,
    }
    with _lock:
        _singleton_events.append(event)
    log.warning(
        "Singleton conflict for agent %s — %s wins (winner=%s, loser=%s)",
        name,
        outcome,
        winner_instance_id or "?",
        loser_instance_id or "?",
    )
    return event


def get_recent_singleton_event(
    name: str, within_seconds: int = SINGLETON_EVENT_WINDOW_S
) -> dict | None:
    """Return the most recent conflict event for ``name`` within the window.

    The dashboard banner / per-agent detail pane fades out once the
    most recent event is older than ``within_seconds``. Default window
    matches HANDOFF.md (last hour).
    """
    cutoff = time.time() - max(0, int(within_seconds))
    with _lock:
        # Iterate newest-first so we can return on the first matching
        # hit. Events are time-ordered globally, so the first matching
        # entry IS the most recent for ``name``; we only return it when
        # it's still inside the window.
        for event in reversed(_singleton_events):
            if event.get("name") != name:
                continue
            if event.get("ts", 0) < cutoff:
                return None
            return dict(event)
    return None
