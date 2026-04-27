"""``POST /api/agents/register`` — REST-level heartbeat for stdlib agents."""

from hub.views.api._common import (
    JsonResponse,
    csrf_exempt,
    json,
    require_http_methods,
)


@csrf_exempt
@require_http_methods(["POST"])
def api_agents_register(request):
    """POST /api/agents/register — REST-level agent registration + heartbeat.

    Intended for lightweight Python/stdlib agents (caduceus) that do not
    run a WebSocket consumer. Accepts JSON:
        {
          "token": "wks_...",
          "name": "caduceus@host",
          "machine": "host",
          "role": "healer",
          "model": "stdlib",
          "channels": ["#general"],
          "orochi_current_task": "monitoring"
        }
    Auth: workspace token in body or query string.
    """
    body = {}
    if request.body:
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "invalid json"}, status=400)

    token = body.get("token") or request.GET.get("token")
    if not token:
        return JsonResponse({"error": "token required"}, status=401)

    from hub.models import WorkspaceToken

    try:
        wt = WorkspaceToken.objects.get(token=token)
    except WorkspaceToken.DoesNotExist:
        return JsonResponse({"error": "invalid token"}, status=401)

    name = (body.get("name") or "").strip()
    if not name:
        return JsonResponse({"error": "name required"}, status=400)

    # Hydrate the agent's channel subscriptions from the DB (the
    # ChannelMembership table is the source of truth, matching the WS
    # register flow). Previously this endpoint hard-coded a
    # ["#general"] default on every heartbeat, which forced every new
    # agent to join #general even when the dashboard user wanted
    # subscriptions to be opt-in.
    #
    # A caller that explicitly sends "channels" (legacy REST clients)
    # is honored for backward-compat; otherwise we use whatever the DB
    # has, which may be an empty list for a brand-new agent.
    import re as _re

    from django.contrib.auth.models import User as _User

    from hub.models import ChannelMembership as _ChannelMembership
    from hub.registry import (
        mark_activity,
        register_agent,
        set_orochi_current_task,
        update_heartbeat,
    )

    _safe_name = _re.sub(r"[^a-zA-Z0-9_.\-]", "-", name)
    _agent_username = f"agent-{_safe_name}"
    _persisted_channels: list[str] = []
    try:
        _agent_user = _User.objects.get(username=_agent_username)
        _persisted_channels = [
            m.channel.name
            for m in _ChannelMembership.objects.filter(
                user=_agent_user,
                channel__workspace_id=wt.workspace_id,
            ).select_related("channel")
        ]
    except _User.DoesNotExist:
        _persisted_channels = []
    _legacy_channels = body.get("channels")
    _effective_channels = (
        list(_legacy_channels)
        if isinstance(_legacy_channels, list)
        else _persisted_channels
    )

    register_agent(
        name=name,
        workspace_id=wt.workspace_id,
        info={
            "agent_id": body.get("agent_id") or name,
            "machine": body.get("machine", ""),
            # #257 — live ``hostname(1)`` of the running agent process.
            # Authoritative "where am I" signal that the frontend badge
            # (hostedAgentName) prefers over ``machine``. Client-supplied
            # from the agent's own ``socket.gethostname()`` / Node
            # ``os.hostname()`` — NEVER derived from the auth token or
            # source IP on the hub side (lead msg#15578: server-side
            # inference was the bug we're fixing).
            "hostname": body.get("hostname", ""),
            # todo#55: canonical FQDN (socket.getfqdn()) from the heartbeat.
            "orochi_hostname_canonical": body.get("orochi_hostname_canonical", ""),
            "role": body.get("role", "agent"),
            "model": body.get("model", ""),
            "workdir": body.get("workdir", ""),
            "channels": _effective_channels,
            # todo#213: claude-hud-style process/runtime metadata pushed by
            # mamba-healer-mba's agent_meta.py --push loop.
            "multiplexer": body.get("multiplexer", ""),
            "project": body.get("project", ""),
            "pid": body.get("pid") or 0,
            "ppid": body.get("ppid") or 0,
            "orochi_context_pct": body.get("orochi_context_pct"),
            # YAML-declared compact policy (strategy / trigger_at_percent /
            # live percent reading from the sac sensor). None when the agent
            # has context_management.strategy=noop or unconfigured.
            "context_management": body.get("context_management"),
            "orochi_skills_loaded": body.get("orochi_skills_loaded") or [],
            "started_at": body.get("started_at", ""),
            "version": body.get("version", ""),
            "runtime": body.get("runtime", ""),
            "orochi_subagent_count": body.get("orochi_subagent_count") or 0,
            # v0.11.0 Agents-tab visibility fields (todo#155). The
            # heartbeat now carries the recent action log, the live
            # tmux pane tail, the workspace CLAUDE.md head, and the
            # MCP server list so the dashboard can render meaningful
            # cards instead of "no task reported".
            "recent_actions": body.get("recent_actions") or [],
            "orochi_pane_tail": body.get("orochi_pane_tail", ""),
            "orochi_pane_tail_block": body.get("orochi_pane_tail_block", ""),
            # todo#47 — ~500 filtered lines of tmux scrollback for the
            # agent-detail "Full pane" toggle. Capped at 32 KB client-side.
            "orochi_pane_tail_full": body.get("orochi_pane_tail_full", ""),
            "claude_md_head": body.get("claude_md_head", ""),
            "mcp_servers": body.get("mcp_servers") or [],
            # todo#265: Claude Code OAuth account public metadata
            # (email, org, subscription state). Strict whitelist —
            # never accept access/refresh tokens or credentials.
            "oauth_email": body.get("oauth_email", ""),
            "oauth_org_name": body.get("oauth_org_name", ""),
            "oauth_account_uuid": body.get("oauth_account_uuid", ""),
            "oauth_display_name": body.get("oauth_display_name", ""),
            "billing_type": body.get("billing_type", ""),
            "has_available_subscription": body.get("has_available_subscription"),
            "usage_disabled_reason": body.get("usage_disabled_reason", ""),
            "has_extra_usage_enabled": body.get("has_extra_usage_enabled"),
            "subscription_created_at": body.get("subscription_created_at", ""),
            # Quota telemetry from statusline parsing
            "quota_5h_pct": body.get("quota_5h_pct"),
            "quota_5h_remaining": body.get("quota_5h_remaining", ""),
            "quota_weekly_pct": body.get("quota_weekly_pct"),
            "quota_weekly_remaining": body.get("quota_weekly_remaining", ""),
            "orochi_statusline_model": body.get("orochi_statusline_model", ""),
            "orochi_account_email": body.get("orochi_account_email", ""),
            # scitex-agent-container heartbeat-push payload. Long names are
            # preferred by the dashboard; accept the short-name aliases too
            # for backward compat with older pushers.
            "quota_5h_used_pct": body.get("quota_5h_used_pct")
            if body.get("quota_5h_used_pct") is not None
            else body.get("quota_5h_pct"),
            "quota_7d_used_pct": body.get("quota_7d_used_pct")
            if body.get("quota_7d_used_pct") is not None
            else body.get("quota_weekly_pct"),
            "quota_5h_reset_at": body.get("quota_5h_reset_at")
            or body.get("quota_5h_remaining", ""),
            "quota_7d_reset_at": body.get("quota_7d_reset_at")
            or body.get("quota_weekly_remaining", ""),
            # Terminal pane + classified state from agent-container.
            "orochi_pane_state": body.get("orochi_pane_state", ""),
            "orochi_stuck_prompt_text": body.get("orochi_stuck_prompt_text", ""),
            "pane_text": body.get("pane_text", ""),
            # Workspace files (full CLAUDE.md, redacted .mcp.json).
            "claude_md": body.get("claude_md", ""),
            "mcp_json": body.get("mcp_json", ""),
            # Claude Code hook-captured events.
            "recent_tools": body.get("recent_tools") or [],
            "recent_prompts": body.get("recent_prompts") or [],
            "agent_calls": body.get("agent_calls") or [],
            "background_tasks": body.get("background_tasks") or [],
            "tool_counts": body.get("tool_counts") or {},
            # Functional-heartbeat shortcuts — last tool use (LLM-level
            # liveness) + last mcp__* tool (proves MCP sidecar route).
            "last_tool_at": body.get("last_tool_at") or "",
            "last_tool_name": body.get("last_tool_name") or "",
            "last_mcp_tool_at": body.get("last_mcp_tool_at") or "",
            "last_mcp_tool_name": body.get("last_mcp_tool_name") or "",
            # PaneAction summary from scitex-agent-container action_store.
            # Surfaces nonce-probe, compact, etc. outcomes on the
            # dashboard without orochi needing to query the per-host DB.
            "last_action_at": body.get("last_action_at") or "",
            "last_action_name": body.get("last_action_name") or "",
            "last_action_outcome": body.get("last_action_outcome") or "",
            "last_action_elapsed_s": body.get("last_action_elapsed_s"),
            "action_counts": body.get("action_counts") or {},
            "p95_elapsed_s_by_action": body.get("p95_elapsed_s_by_action") or {},
            # lead msg#16005: whole ``scitex-agent-container status
            # --terse --json`` dict forwarded by the orochi heartbeat
            # pusher. Passed straight through to ``register_agent`` so
            # new fields added to sac's terse projection land in the
            # registry (and on ``/api/agents/``) automatically.
            "sac_status": body.get("sac_status") or {},
            # msg#16406 / msg#16408 Phase 2 — orochi-cron daemon state
            # reported by ``scitex-orochi heartbeat-push``. List of job
            # dicts (see scitex_orochi._cron._state.render_cron_jobs)
            # that the Machines tab cron panel + ``/api/cron/`` aggregator
            # key off. Absent / empty list preserves the previous value
            # in ``register_agent`` (transient read glitch on the local
            # state file doesn't wipe the UI every 30s).
            "cron_jobs": body.get("cron_jobs") or [],
        },
    )
    # Persist orochi_subagent_count separately — register_agent() preserves prev
    # value if it exists, so we must set it explicitly on every push to
    # reflect current reality.
    if body.get("orochi_subagent_count") is not None:
        from hub.registry import set_orochi_subagent_count

        set_orochi_subagent_count(name, int(body.get("orochi_subagent_count") or 0))
    # Full subagent list push (Lane B #132/#155)
    if body.get("subagents") is not None:
        from hub.registry import set_subagents

        set_subagents(name, body.get("subagents") or [])
    update_heartbeat(name, metrics=body.get("metrics") or {})
    task = body.get("orochi_current_task") or ""
    if task:
        set_orochi_current_task(name, task)
    preview = body.get("last_message_preview") or ""
    if preview:
        mark_activity(name, action=preview)
    return JsonResponse({"status": "ok", "name": name})
