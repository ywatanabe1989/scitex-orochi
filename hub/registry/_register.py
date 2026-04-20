"""Agent + connection (un)registration.

``register_agent`` carries the prev-preserve field list — every per-agent
field that must survive a re-register (heartbeat / WS reconnect) without
flickering. New per-agent fields MUST be added here, otherwise the LEDs
flicker every heartbeat (regression hazard).
"""

import time

from ._store import _active_session_count, _agents, _connections, _lock


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
            # todo#46 — preserve ping/pong state across re-registers
            # (heartbeat, WS reconnect). Without this, every heartbeat
            # wiped last_pong_ts/last_rtt_ms back to absent, so the RT
            # lamp flickered to gray 1× per 30s heartbeat cycle.
            "last_pong_ts": prev.get("last_pong_ts"),
            "last_rtt_ms": prev.get("last_rtt_ms"),
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
