"""Hook-event ring-buffer summary via scitex-agent-container."""

from __future__ import annotations

import json
import subprocess

# Mapping: sac status --json key → heartbeat payload key (sac_hooks_ prefix).
# The sac outputs unprefixed field names; we add sac_hooks_ here so the hub
# registry can namespace them without coupling to the sac key names.
_SAC_TO_HUB: dict[str, str] = {
    "recent_tools": "sac_hooks_recent_tools",
    "recent_prompts": "sac_hooks_recent_prompts",
    "tool_counts": "sac_hooks_tool_counts",
    "last_tool_name": "sac_hooks_last_tool_name",
    "last_tool_at": "sac_hooks_last_tool_at",
    "last_mcp_tool_name": "sac_hooks_last_mcp_tool_name",
    "last_mcp_tool_at": "sac_hooks_last_mcp_tool_at",
    "last_action_name": "sac_hooks_last_action_name",
    "last_action_at": "sac_hooks_last_action_at",
    "last_action_outcome": "sac_hooks_last_action_outcome",
    "last_action_elapsed_s": "sac_hooks_last_action_elapsed_s",
    "p95_elapsed_s_by_action": "sac_hooks_p95_elapsed_s_by_action",
    # scitex-orochi #132 — subagent activity.
    "agent_calls": "sac_hooks_agent_calls",
    "background_tasks": "sac_hooks_background_tasks",
    # scitex-orochi #133 — stuck-subagent detection via LIFO open-call tracking.
    "open_agent_calls": "sac_hooks_open_agent_calls",
    "open_agent_calls_count": "sac_hooks_open_agent_calls_count",
    "oldest_open_agent_age_s": "sac_hooks_oldest_open_agent_age_s",
    # Pass-through (already has the right name for the hub).
    "subagents": "subagents",
}


def _collect_hook_events(agent: str) -> dict:
    """Read hook-event ring-buffer summary via scitex-agent-container.

    scitex-orochi todo#187 / #59: the per-agent Last tool / Last MCP /
    Last action rows stay empty because this heartbeat script never
    pulled these fields from the hook-event ring buffer. Shell-out is
    short-lived (<1 s) and bounded by ``timeout``; on any failure we
    return an empty dict so the rest of the heartbeat still flows.

    The sac ``status --json`` output uses unprefixed field names
    (``recent_tools``, ``agent_calls``, …). This function re-maps them
    to the ``sac_hooks_`` namespace expected by the hub registry so the
    hub can namespace sac data without coupling to sac's key names.
    """
    try:
        proc = subprocess.run(
            ["scitex-agent-container", "status", agent, "--json"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode != 0:
            return {}
        data = json.loads(proc.stdout or "{}")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return {}
    return {hub_key: data[sac_key] for sac_key, hub_key in _SAC_TO_HUB.items() if sac_key in data}
