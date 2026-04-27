"""Hook-event ring-buffer summary via scitex-agent-container."""

from __future__ import annotations

import json
import subprocess

_HOOK_EVENT_KEYS = (
    "sac_hooks_recent_tools",
    "sac_hooks_recent_prompts",
    "sac_hooks_tool_counts",
    "sac_hooks_last_tool_name",
    "sac_hooks_last_tool_at",
    "sac_hooks_last_mcp_tool_name",
    "sac_hooks_last_mcp_tool_at",
    "sac_hooks_last_action_name",
    "last_action_at",
    "last_action_outcome",
    "last_action_elapsed_s",
    "sac_hooks_p95_elapsed_s_by_action",
    # scitex-orochi #132 — subagent activity. sac_hooks_agent_calls is the
    # projected Agent/Task tool-invocation ring buffer; subagents is
    # the in-flight list with descriptions; background_tasks is
    # run_in_background Bash calls.
    "sac_hooks_agent_calls",
    "background_tasks",
    "subagents",
)


def _collect_hook_events(agent: str) -> dict:
    """Read hook-event ring-buffer summary via scitex-agent-container.

    scitex-orochi todo#187 / #59: the per-agent Last tool / Last MCP /
    Last action rows stay empty because this heartbeat script never
    pulled these fields from the hook-event ring buffer. Shell-out is
    short-lived (<1 s) and bounded by ``timeout``; on any failure we
    return an empty dict so the rest of the heartbeat still flows.
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
    return {k: data[k] for k in _HOOK_EVENT_KEYS if k in data}
