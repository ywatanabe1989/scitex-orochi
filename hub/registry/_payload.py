"""Dashboard payload assembly + derived liveness for the Agents tab.

``get_agents`` is the canonical read path: it cleans up stale entries,
merges persistent ``AgentProfile`` rows over transient register-time
state, computes derived ``liveness`` (online / idle / stale), and
returns a list of dicts shaped for the dashboard JSON payload.
"""

import time

from ._store import _active_session_count, _agents, _cleanup_locked, _lock


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
                    # todo#305 Task 7 (lead msg#15548): per-agent
                    # is_hidden flag; dashboard's 👁 eye toggle reads
                    # this to dim / drop agent cards in sidebar + graph.
                    "is_hidden": bool(getattr(p, "is_hidden", False)),
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
        # Prefer the pane_state classifier (agent_meta_pkg/_classifier.py)
        # which already separates "idle at prompt" (alive, waiting) from
        # "stale" (3+ cycles unchanged, no busy markers — actually stuck).
        # Falls back to the last_action timer when pane_state is missing.
        liveness = a.get("status", "online")
        pane = (a.get("pane_state") or "").lower()
        idle_seconds = None
        if action_ts:
            idle_seconds = int(now - action_ts)
        if a.get("status") == "online":
            if pane == "running":
                liveness = "online"
            elif pane == "stale" or pane == "auth_error":
                liveness = "stale"
            elif pane == "idle":
                liveness = "idle"
            elif pane in (
                "compose_pending_unsent",
                "bypass_permissions_prompt",
                "dev_channels_prompt",
                "y_n_prompt",
            ):
                liveness = "idle"  # awaiting input — not stuck
            elif idle_seconds is not None:
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
                # #257 — live ``hostname(1)`` reported by the heartbeat.
                # This is the authoritative "where is this process
                # running right now" field. The frontend badge
                # (hostedAgentName) prefers ``hostname`` over
                # ``machine`` because the latter can drift (stale
                # YAML label / env override) while the former is the
                # kernel's answer from the live process. Exposed here
                # so the sidebar card shows ``proj-neurovista@spartan``
                # correctly even when an env var says otherwise (lead
                # msg#15578 fix).
                "hostname": a.get("hostname", ""),
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
                # todo#305 Task 7 (lead msg#15548): persistent per-agent
                # hidden flag. False by default for agents without a
                # profile row. Frontend 👁 toggle reads this to dim / drop
                # the agent card in sidebar + topology.
                "is_hidden": bool(prof.get("is_hidden", False)),
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
                # #259 — 4th-indicator (Remote / nonce-echo) round-trip
                # data for the dashboard. ``last_nonce_echo_at`` is the
                # field the LED renderer reads (already wired in
                # agent-badge.js); the other two surface RTT + raw unix
                # timestamp for tooling and the per-agent detail page.
                "last_nonce_echo_at": a.get("last_nonce_echo_at"),
                "last_echo_rtt_ms": a.get("last_echo_rtt_ms"),
                "last_echo_ok_ts": (
                    datetime.fromtimestamp(
                        a["last_echo_ok_ts"], tz=timezone.utc
                    ).isoformat()
                    if a.get("last_echo_ok_ts")
                    else None
                ),
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
                "context_management": a.get("context_management"),
                "skills_loaded": list(a.get("skills_loaded") or []),
                "started_at": a.get("started_at", ""),
                "version": a.get("version", ""),
                "runtime": a.get("runtime", ""),
                # v0.11.0 Agents-tab visibility fields.
                "recent_actions": list(a.get("recent_actions") or []),
                "orochi_pane_tail": a.get("orochi_pane_tail", ""),
                "orochi_pane_tail_block": a.get("orochi_pane_tail_block", ""),
                # todo#47 — full scrollback; empty string if the agent
                # hasn't pushed the new field yet.
                "orochi_pane_tail_full": a.get("orochi_pane_tail_full", ""),
                "claude_md_head": a.get("claude_md_head", ""),
                "mcp_json": a.get("mcp_json", ""),
                "pane_state": a.get("pane_state", ""),
                "orochi_stuck_prompt_text": a.get("orochi_stuck_prompt_text", ""),
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
                # lead msg#16005 — whole ``scitex-agent-container status
                # --terse --json`` payload. Dashboard consumers (Agents
                # tab, future dashboards) can key off
                # ``sac_status.<any-field>`` without this module needing
                # a per-field allowlist. ``--terse`` projects the source
                # onto dotted keys (see
                # scitex_agent_container.terse.TERSE_STATUS_FIELDS) so
                # flat reads via ``a["sac_status"]["context_management.percent"]``
                # work today and on whatever fields get added tomorrow.
                "sac_status": dict(a.get("sac_status") or {}),
                # Orochi unified cron state (msg#16406 / msg#16408 Phase 2).
                # Per-heartbeat snapshot of the local orochi-cron daemon's job
                # list (empty list when the daemon isn't running on this host).
                # Consumed by /api/cron/ and the Machines tab cron-jobs panel.
                "cron_jobs": list(a.get("cron_jobs") or []),
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
