"""Agent + connection (un)registration.

``register_agent`` carries the prev-preserve field list — every per-agent
field that must survive a re-register (heartbeat / WS reconnect) without
flickering. New per-agent fields MUST be added here, otherwise the LEDs
flicker every heartbeat (regression hazard).
"""

import logging
import time

from ._store import (
    SINGLETON_EVENT_WINDOW_S,
    _active_session_count,
    _agents,
    _connection_identity,
    _connections,
    _lock,
    _singleton_events,
)

_log = logging.getLogger("orochi.registry")


def register_agent(name: str, workspace_id: int, info: dict) -> None:
    """Register or update an agent.

    Re-registration (e.g. WS reconnect) preserves narrative state that
    the agent populated via later calls — orochi_current_task, last_message,
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
            "orochi_hostname_canonical": info.get("orochi_hostname_canonical", "")
            or prev.get("orochi_hostname_canonical", ""),
            # ── #257 canonical heartbeat metadata ─────────────────────
            # `hostname` is what `hostname(1)` returns on the running
            # process — single source of truth for "where am I", per
            # ywatanabe msg #14726/#14730: never display a fabricated or
            # cached @host label. Distinct from `machine` (YAML config
            # label) and `orochi_hostname_canonical` (FQDN via getfqdn()).
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
            "instance_id": info.get("instance_id", "") or prev.get("instance_id", ""),
            # A2A protocol surface URL for this agent (Tier 3 same-host
            # optimization). When present and reachable, the hub's A2A
            # dispatch view (api_a2a_dispatch) HTTP-POSTs directly to
            # this URL instead of going through WS group_send. Empty
            # string means "WS-only routing"; agents without a sidecar
            # A2A server omit this and the hub falls back to WS.
            # Preserved across re-registers — same prev-preserve pattern
            # as instance_id.
            "a2a_url": info.get("a2a_url", "") or prev.get("a2a_url", ""),
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
            "orochi_claude_md": info.get("orochi_claude_md", "") or prev.get("orochi_claude_md", ""),
            "status": "online",
            "registered_at": prev.get("registered_at") or time.time(),
            "last_heartbeat": time.time(),
            "last_action": prev.get("last_action") or time.time(),
            "last_message_preview": prev.get("last_message_preview", ""),
            "orochi_current_task": prev.get("orochi_current_task", ""),
            "orochi_subagent_count": prev.get("orochi_subagent_count", 0),
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
            # Same prev-preserve pitfall as the ping/pong fields above:
            # if these were dropped on every heartbeat, the 4th LED
            # (Remote/echo) would flicker to grey-pending at the
            # heartbeat cadence even when the echo path is live. The
            # fields are written by ``update_echo_pong()`` (in
            # ``_heartbeat.py``) when an ``echo_pong`` frame lands, and
            # are surfaced in the API by ``_payload.get_agents()`` /
            # ``hub/views/agent_detail.py``.
            "last_echo_rtt_ms": prev.get("last_echo_rtt_ms"),
            "last_echo_ok_ts": prev.get("last_echo_ok_ts"),
            "last_nonce_echo_at": prev.get("last_nonce_echo_at"),
            # Extended process/runtime metadata pushed by agent_meta.py --push.
            # Optional; absent for legacy WS-only agents.
            "pid": info.get("pid") or prev.get("pid") or 0,
            "ppid": info.get("ppid") or prev.get("ppid") or 0,
            "orochi_context_pct": (
                info.get("orochi_context_pct")
                if info.get("orochi_context_pct") is not None
                else prev.get("orochi_context_pct")
            ),
            # YAML compact policy block from sac status. Preserve across
            # heartbeats so the Agents tab keeps showing the threshold even
            # when an individual heartbeat omits it (legacy clients).
            "context_management": (
                info.get("context_management")
                if info.get("context_management") is not None
                else prev.get("context_management")
            ),
            "orochi_skills_loaded": (
                list(info.get("orochi_skills_loaded"))
                if isinstance(info.get("orochi_skills_loaded"), (list, tuple))
                else prev.get("orochi_skills_loaded") or []
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
            "orochi_pane_tail": info.get("orochi_pane_tail") or prev.get("orochi_pane_tail") or "",
            "orochi_pane_tail_block": info.get("orochi_pane_tail_block")
            or prev.get("orochi_pane_tail_block")
            or "",
            # todo#47 — full-scrollback pane for the web-terminal viewer.
            # Pushed by agent_meta.py --push when the client is new
            # enough; older clients never populate it and the UI
            # gracefully falls back to the short orochi_pane_tail_block.
            "orochi_pane_tail_full": info.get("orochi_pane_tail_full")
            or prev.get("orochi_pane_tail_full")
            or "",
            "orochi_claude_md_head": info.get("orochi_claude_md_head")
            or prev.get("orochi_claude_md_head")
            or "",
            # todo#460: full .mcp.json content for the Agents tab file viewer.
            # agent_meta.py --push (dotfiles PR #71) sends a size-capped,
            # token-redacted copy of the workspace `.mcp.json`. Absent for
            # legacy WS-only agents; falls through to the empty string.
            "orochi_mcp_json": info.get("orochi_mcp_json") or prev.get("orochi_mcp_json") or "",
            # todo#418: agent decision-transparency fields for the Agents tab.
            # `orochi_pane_state` is the classifier label (`running` / `waiting` /
            # `y_n_prompt` / `compose_pending_unsent` / `auth_error` / etc.)
            # computed by agent_meta.py --push using the same classifiers
            # fleet-prompt-actuator uses (scitex_agent_container.runtimes.
            # prompts + detect_compose_pending). `orochi_stuck_prompt_text` carries
            # the verbatim prompt so ywatanabe / dashboard viewers can see
            # what the agent is blocked on. Both empty when agent_meta can't
            # classify or the agent is a legacy WS-only pusher.
            "orochi_pane_state": info.get("orochi_pane_state") or prev.get("orochi_pane_state") or "",
            "orochi_stuck_prompt_text": info.get("orochi_stuck_prompt_text")
            or prev.get("orochi_stuck_prompt_text")
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
            "sac_hooks_agent_calls": (
                list(info.get("sac_hooks_agent_calls"))
                if isinstance(info.get("sac_hooks_agent_calls"), (list, tuple))
                else prev.get("sac_hooks_agent_calls") or []
            ),
            "background_tasks": (
                list(info.get("background_tasks"))
                if isinstance(info.get("background_tasks"), (list, tuple))
                else prev.get("background_tasks") or []
            ),
            "sac_hooks_tool_counts": (
                dict(info.get("sac_hooks_tool_counts"))
                if isinstance(info.get("sac_hooks_tool_counts"), dict)
                else prev.get("sac_hooks_tool_counts") or {}
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
            "sac_hooks_p95_elapsed_s_by_action": (
                dict(info.get("sac_hooks_p95_elapsed_s_by_action"))
                if isinstance(info.get("sac_hooks_p95_elapsed_s_by_action"), dict)
                else prev.get("sac_hooks_p95_elapsed_s_by_action") or {}
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
            # todo#272 — per-window quota state machine slot (ok / warn /
            # escalate). Owned by ``hub.quota_watch.check_agent_quota_pressure``
            # which reads it before evaluate() and writes the new state
            # after. Preserved across heartbeats so threshold transitions
            # fire exactly once per crossing — without the prev-preserve
            # the state machine would reset to "ok" every heartbeat and
            # re-post warn / escalate on every poll (spam regression).
            "quota_state_5h": prev.get("quota_state_5h") or "ok",
            "quota_state_7d": prev.get("quota_state_7d") or "ok",
            # msg#16388 — server-side auto-dispatch streak + cooldown state.
            # Owned by ``hub.auto_dispatch.check_agent_auto_dispatch``. Same
            # prev-preserve pattern as quota_state_*: without it every
            # heartbeat would reset the streak to 0 and the firing
            # condition (N consecutive zero readings) could never be met.
            "idle_streak": prev.get("idle_streak") or 0,
            "auto_dispatch_last_fire_ts": prev.get("auto_dispatch_last_fire_ts"),
            "orochi_mcp_servers": (
                list(info.get("orochi_mcp_servers"))
                if isinstance(info.get("orochi_mcp_servers"), (list, tuple))
                else prev.get("orochi_mcp_servers") or []
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
            "orochi_quota_5h_pct": (
                info.get("orochi_quota_5h_pct")
                if info.get("orochi_quota_5h_pct") is not None
                else prev.get("orochi_quota_5h_pct")
            ),
            "orochi_quota_5h_remaining": info.get("orochi_quota_5h_remaining")
            or prev.get("orochi_quota_5h_remaining")
            or "",
            "orochi_quota_weekly_pct": (
                info.get("orochi_quota_weekly_pct")
                if info.get("orochi_quota_weekly_pct") is not None
                else prev.get("orochi_quota_weekly_pct")
            ),
            "orochi_quota_weekly_remaining": info.get("orochi_quota_weekly_remaining")
            or prev.get("orochi_quota_weekly_remaining")
            or "",
            "orochi_statusline_model": info.get("orochi_statusline_model")
            or prev.get("orochi_statusline_model")
            or "",
            "orochi_account_email": info.get("orochi_account_email")
            or prev.get("orochi_account_email")
            or "",
            # lead msg#16005: full ``scitex-agent-container status --terse
            # --json`` dict attached to the heartbeat by the pusher
            # (``scripts/client/agent_meta_pkg/_sac_status.py``). Stored
            # verbatim so future fields added to sac's terse projection
            # (orochi_context_pct, orochi_pane_state, orochi_current_tool, quota, ...) reach
            # the dashboard via ``/api/agents/`` without per-field
            # plumbing here.
            #
            # Replace-on-present semantics: a fresh heartbeat carrying
            # a non-empty dict always wins (the pusher re-runs sac
            # every cycle, so the value is current). Absent / empty
            # dict falls back to the previous value — older pushers
            # that don't emit the field yet don't wipe it.
            "sac_status": (
                dict(info.get("sac_status"))
                if isinstance(info.get("sac_status"), dict) and info.get("sac_status")
                else prev.get("sac_status") or {}
            ),
            # Orochi unified cron state (msg#16406 / msg#16408 Phase 2).
            # List of {name, interval, last_run, last_exit, last_skipped,
            # last_duration_seconds, next_run, running, disabled, command,
            # timeout} dicts produced by scitex_orochi._cron.render_cron_jobs
            # and attached to every heartbeat by ``scitex-orochi heartbeat-push``.
            # Source of truth for the Machines tab cron-jobs panel + the
            # ``/api/cron/`` aggregator.
            #
            # Replace-on-present semantics: a heartbeat carrying a non-empty
            # list always wins (the pusher re-runs the state reader every
            # cycle, so the value is current). An empty list or absent field
            # falls back to the previous value — a transient read glitch on
            # the local state file doesn't blank the UI every 30s.
            "cron_jobs": (
                list(info.get("cron_jobs"))
                if isinstance(info.get("cron_jobs"), (list, tuple))
                and info.get("cron_jobs")
                else prev.get("cron_jobs") or []
            ),
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


# ── scitex-orochi#255: singleton cardinality enforcement ────────────────
#
# When two WS connections claim the same agent name, the hub picks one
# and disconnects the other. The decision is made on the (instance_id,
# start_ts_unix) pair captured per-connection at connect time:
#
#   * If both sides report the pair, the older ``start_ts_unix`` wins
#     (the original process keeps its claim — newer racers lose).
#   * If either side is missing the pair (legacy clients), we don't
#     enforce — the running connection wins by default and we log a
#     WARNING so multi-instance hazards are still visible in logs.
#
# State lives next to ``_connections`` in ``_store.py``:
#
#   * ``_connection_identity[channel_name]`` — the captured triple for
#     this WS, set at connect / cleared at disconnect.
#   * ``_singleton_events[agent_name]`` — bounded ring buffer of recent
#     conflict events (``SINGLETON_EVENT_WINDOW_S`` window) so the
#     agent-detail API can surface the newest one.


def set_connection_identity(
    channel_name: str,
    agent_name: str,
    instance_id: str | None,
    start_ts_unix: float | None,
) -> None:
    """Remember the (agent, instance_id, start_ts_unix) of a live WS.

    Called from ``AgentConsumer.connect`` after the workspace token has
    authorized the connection. The recorded triple is what the singleton
    decider compares against on a subsequent connection that claims the
    same ``agent_name``.

    ``instance_id`` and ``start_ts_unix`` may be ``None``/empty for
    legacy clients — they are stored as-is so the decider can detect
    "missing identity" and fall back to the permissive multi-connection
    behaviour without enforcement.
    """
    if not channel_name:
        return
    with _lock:
        _connection_identity[channel_name] = {
            "agent_name": agent_name or "",
            "instance_id": (instance_id or "") if isinstance(instance_id, str) else "",
            "start_ts_unix": (
                float(start_ts_unix)
                if isinstance(start_ts_unix, (int, float))
                else None
            ),
        }


def clear_connection_identity(channel_name: str) -> None:
    """Drop the identity row for ``channel_name`` (called on disconnect)."""
    if not channel_name:
        return
    with _lock:
        _connection_identity.pop(channel_name, None)


def get_connection_identity(channel_name: str) -> dict | None:
    """Return the captured identity triple for a WS, or ``None`` if absent."""
    if not channel_name:
        return None
    with _lock:
        ident = _connection_identity.get(channel_name)
        return dict(ident) if ident else None


def list_sibling_channels(agent_name: str) -> list[str]:
    """Return the live ``channel_name`` ids currently registered for an agent.

    Used by the singleton enforcer to find the incumbent connection so
    it can compare identities and (when the new one wins) close the
    incumbent. Returns an empty list when the agent has no live
    connections (the new WS is the first claimant — no enforcement
    needed).
    """
    if not agent_name:
        return []
    with _lock:
        return list(_connections.get(agent_name, ()))


def decide_singleton_winner(
    name: str,
    new_instance_id: str | None,
    new_start_ts_unix: float | None,
) -> str:
    """Decide who survives when two WS claim the same ``name``.

    Returns one of:

    * ``"challenger"`` — the new connection wins (the existing/incumbent
      connection should be closed).
    * ``"incumbent"`` — the existing connection wins (the new/challenger
      connection should be closed).
    * ``"no_enforcement"`` — either side is missing the
      ``(instance_id, start_ts_unix)`` pair, so we fall back to the
      permissive multi-connection behaviour. Caller logs a WARNING and
      keeps both sockets alive.

    Algorithm — the older ``start_ts_unix`` wins (the original process
    keeps its claim). Ties and missing data fall through to
    ``no_enforcement`` rather than guessing — disrupting a healthy
    incumbent on insufficient evidence is the worst outcome.

    Requires the lock-free read of ``_connection_identity`` /
    ``_connections`` to find the incumbent's recorded identity.
    """
    if not name:
        return "no_enforcement"
    if not isinstance(new_instance_id, str) or not new_instance_id:
        return "no_enforcement"
    if not isinstance(new_start_ts_unix, (int, float)):
        return "no_enforcement"

    with _lock:
        sibling_channels = list(_connections.get(name, ()))
        # Pick the most-recent incumbent identity among the siblings.
        # In practice there's exactly one incumbent at the point of
        # comparison (the new WS hasn't yet been added). If multiple
        # siblings exist with full identity, we compare against the
        # one with the OLDEST start_ts_unix — that is the de-facto
        # primary that a challenger must beat.
        incumbent: dict | None = None
        for ch in sibling_channels:
            ident = _connection_identity.get(ch)
            if not ident:
                continue
            if not ident.get("instance_id"):
                continue
            if not isinstance(ident.get("start_ts_unix"), (int, float)):
                continue
            if incumbent is None or float(ident["start_ts_unix"]) < float(
                incumbent["start_ts_unix"]
            ):
                incumbent = ident

    if incumbent is None:
        # No incumbent with enforceable identity — fall back to
        # permissive behaviour. Caller logs the situation.
        return "no_enforcement"

    incumbent_start = float(incumbent["start_ts_unix"])
    new_start = float(new_start_ts_unix)
    if new_start < incumbent_start:
        # Challenger is older → it wins.
        return "challenger"
    # Incumbent is older OR tie. Don't disrupt the running process.
    return "incumbent"


def record_singleton_conflict(
    name: str,
    winner_instance_id: str,
    loser_instance_id: str,
    reason: str = "duplicate_identity",
) -> None:
    """Append a conflict event to the per-agent ring buffer.

    Trims entries older than ``SINGLETON_EVENT_WINDOW_S`` so the buffer
    stays bounded over a long-running hub process. The agent-detail
    API surfaces the newest entry as ``last_duplicate_identity_event``.
    """
    if not name:
        return
    now = time.time()
    cutoff = now - SINGLETON_EVENT_WINDOW_S
    with _lock:
        events = _singleton_events.setdefault(name, [])
        events.append(
            {
                "ts": now,
                "agent": name,
                "winner_instance_id": winner_instance_id or "",
                "loser_instance_id": loser_instance_id or "",
                "reason": reason or "duplicate_identity",
            }
        )
        # Drop stale events. List ops are cheap at this size (<< 100/hr).
        _singleton_events[name] = [e for e in events if e["ts"] >= cutoff]


def get_recent_singleton_event(name: str) -> dict | None:
    """Return the newest singleton-conflict event for ``name`` (or None).

    Lazy-trims the per-agent buffer to the active window. Returns a
    plain dict (a copy) so the caller can mutate it freely.
    """
    if not name:
        return None
    cutoff = time.time() - SINGLETON_EVENT_WINDOW_S
    with _lock:
        events = _singleton_events.get(name) or []
        fresh = [e for e in events if e["ts"] >= cutoff]
        if fresh != events:
            if fresh:
                _singleton_events[name] = fresh
            else:
                _singleton_events.pop(name, None)
        if not fresh:
            return None
        # Newest last (append-only) → return the tail.
        return dict(fresh[-1])
