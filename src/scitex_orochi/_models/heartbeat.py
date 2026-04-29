"""Canonical heartbeat field registry.

The heartbeat payload's field set is currently duplicated across six
files:

  1. ``scripts/client/_collect_agent_metadata/_collect.py``  (producer
     status dict)
  2. ``src/scitex_orochi/_cli/commands/heartbeat_cmd.py``    (forwarder)
  3. ``hub/views/api/_agents_register.py``                   (consumer
     register_agent kwargs)
  4. ``hub/registry/_register.py``                           (storage)
  5. ``hub/views/agent_detail.py``                           (rendering)
  6. ``hub/frontend/src/agents-tab/{overview,detail}.ts``    (UI)

Adding a new field today means a 6-file diff with no type-checker
glue between the parts. Past audits surfaced this as the dominant
risk during prefix migrations (e.g. the ``orochi_*``/``sac_*``
re-prefix wave 2026-04-22 → 2026-04-27).

This module is the **first** consolidation step (EI-2026-04-28 §7,
MVP scope). It defines:

* :class:`HeartbeatField` — name + default + one-line `notes` for
  documentation.
* :data:`HEARTBEAT_FIELDS` — the ordered list of every field that
  currently flows on the wire.
* :data:`HEARTBEAT_FIELD_NAMES` — convenience set for membership tests.

The pattern of incremental adoption (instead of a half-day rewrite):

* New code uses the registry directly.
* Old code stays as-is until each file is migrated; tests pin that
  the registry is a superset of what each file currently expects.
* Once every consumer reads from the registry, the duplication is
  gone and adding a field becomes a 1-file diff.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HeartbeatField:
    """Canonical descriptor for one heartbeat payload field."""

    name: str
    """Wire-format field name. Lowercase + underscores. Prefix
    convention: ``orochi_*`` for fields the orochi heartbeat path
    derives, ``sac_*`` for fields forwarded from
    scitex-agent-container, ``oauth_*`` for Claude Code OAuth public
    metadata."""

    default: Any
    """Value to substitute when the producer didn't send the key.
    Empty-string for strings, ``[]`` for lists, ``{}`` for dicts,
    ``0`` for counters, ``None`` for "actually missing" semantics
    (the dashboard should special-case None vs 0 vs '')."""

    notes: str = ""
    """One-line operator-facing note. Renders into the API docs and
    helps the reviewer evaluate "do we still need this field?" """


# Sorted into rough categories so additions land near related fields,
# not at the end of an alphabetical jumble. Categories:
#  - identity         (who is this agent)
#  - process          (PID-level facts)
#  - context          (LLM-side state: tokens, current task)
#  - quota            (Claude Code subscription window state)
#  - host metrics     (machine-level metrics, multi-host dedupe concern)
#  - pane / multiplex (terminal capture + classifier verdict)
#  - workspace files  (CLAUDE.md / .mcp.json / .env viewers)
#  - sac_hooks        (Claude Code hook events forwarded by sac)
#  - oauth            (Claude Code account public metadata)
#  - meta             (deploy version, schema version)
HEARTBEAT_FIELDS: tuple[HeartbeatField, ...] = (
    # ---- identity ---------------------------------------------------
    HeartbeatField("name", "", "agent display name (e.g. healer@mba)"),
    HeartbeatField("agent_id", "", "stable identifier; defaults to name"),
    HeartbeatField("machine", "", "canonical_name from orochi-machines.yaml"),
    HeartbeatField("hostname", "", "live socket.gethostname() of the agent"),
    HeartbeatField(
        "orochi_hostname_canonical", "", "canonical FQDN from socket.getfqdn()"
    ),
    HeartbeatField("role", "agent", "head / healer / specialist / agent"),
    HeartbeatField("model", "", "underlying LLM model name"),
    HeartbeatField("workdir", "", "current working directory"),
    HeartbeatField("project", "", "project label, defaults to agent name"),
    HeartbeatField("multiplexer", "", "tmux / screen / none"),
    # ---- process ----------------------------------------------------
    HeartbeatField("pid", 0, "OS PID of the agent process"),
    HeartbeatField("ppid", 0, "parent PID"),
    HeartbeatField("started_at", "", "ISO-8601 process start time"),
    HeartbeatField("runtime", "", "python / node / shell"),
    HeartbeatField("version", "", "agent / package version"),
    # ---- context ----------------------------------------------------
    HeartbeatField(
        "orochi_context_pct",
        None,
        "live context-window utilization percentage; None when unknown",
    ),
    HeartbeatField(
        "context_management",
        None,
        "YAML compact policy: strategy + trigger_at_percent",
    ),
    HeartbeatField("orochi_current_task", "", "human-readable current task"),
    HeartbeatField("orochi_current_tool", "", "live MCP tool name in flight"),
    HeartbeatField("orochi_subagent_count", 0, "count of running subagents"),
    HeartbeatField("subagents", [], "full list of subagent metadata dicts"),
    HeartbeatField("orochi_skills_loaded", [], "skills the agent has loaded"),
    HeartbeatField("orochi_mcp_servers", [], "MCP server names the agent runs"),
    # ---- quota ------------------------------------------------------
    HeartbeatField("quota_5h_used_pct", None, "Claude Code 5-hour quota window used %"),
    HeartbeatField("quota_7d_used_pct", None, "Claude Code weekly quota window used %"),
    HeartbeatField("quota_5h_reset_at", "", "ISO-8601 next 5-hour quota reset"),
    HeartbeatField("quota_7d_reset_at", "", "ISO-8601 next weekly quota reset"),
    HeartbeatField(
        "orochi_account_email", "", "email behind the active Claude Code OAuth"
    ),
    # ---- host metrics ----------------------------------------------
    HeartbeatField(
        "metrics", {}, "machine-level metrics dict; dedup'd hub-side per host"
    ),
    # ---- pane / multiplex ------------------------------------------
    HeartbeatField("pane_text", "", "raw tmux pane capture (last N lines)"),
    HeartbeatField("orochi_pane_tail", "", "filtered pane tail (cosmetic clean)"),
    HeartbeatField(
        "orochi_pane_tail_block", "", "block-quoted tail for dashboard render"
    ),
    HeartbeatField(
        "orochi_pane_tail_full",
        "",
        "~500 lines of tmux scrollback for the Full-pane viewer",
    ),
    HeartbeatField(
        "orochi_pane_state",
        "",
        "classifier verdict: running / stuck_prompt / auth_error / etc.",
    ),
    HeartbeatField(
        "orochi_stuck_prompt_text",
        "",
        "verbatim prompt the agent is blocked on (empty when running)",
    ),
    HeartbeatField("recent_actions", [], "deprecated v0.10 action log"),
    # ---- workspace files -------------------------------------------
    HeartbeatField("orochi_claude_md", "", "redacted CLAUDE.md body"),
    HeartbeatField("orochi_claude_md_head", "", "first non-blank line of CLAUDE.md"),
    HeartbeatField("orochi_mcp_json", "", "redacted .mcp.json body"),
    HeartbeatField(
        "orochi_env_file",
        "",
        "redacted .env body (see _files.py::_redact_env_text for the layered defenses)",
    ),
    # ---- sac hooks -------------------------------------------------
    HeartbeatField(
        "sac_hooks_recent_tools",
        [],
        "Claude Code tool-use events captured by scitex-agent-container",
    ),
    HeartbeatField("sac_hooks_recent_prompts", [], "user-prompt events"),
    HeartbeatField("sac_hooks_agent_calls", [], "subagent-spawn events"),
    HeartbeatField("sac_hooks_background_tasks", [], "Background-task events"),
    # orochi#133 — stuck-subagent detection (sac-side LIFO open-call tracking).
    HeartbeatField("sac_hooks_open_agent_calls", [], "Agent pretool events with no posttool (potentially stuck)"),
    HeartbeatField("sac_hooks_open_agent_calls_count", 0, "count of open (unmatched) Agent calls"),
    HeartbeatField("sac_hooks_oldest_open_agent_age_s", None, "age_seconds of oldest open Agent call"),
    HeartbeatField(
        "sac_hooks_tool_counts", {}, "per-tool count map for the dashboard chip"
    ),
    HeartbeatField("sac_hooks_last_tool_at", "", "ISO-8601 last tool-use timestamp"),
    HeartbeatField("sac_hooks_last_tool_name", "", "name of last tool used"),
    HeartbeatField("sac_hooks_last_mcp_tool_at", "", "last mcp__* tool timestamp"),
    HeartbeatField("sac_hooks_last_mcp_tool_name", "", "name of last mcp__ tool"),
    HeartbeatField("sac_hooks_last_action_at", "", "PaneAction last-event time"),
    HeartbeatField("sac_hooks_last_action_name", "", "PaneAction last-event name"),
    HeartbeatField(
        "sac_hooks_last_action_outcome",
        "",
        "PaneAction last-event outcome (success/failure/timeout)",
    ),
    HeartbeatField(
        "sac_hooks_last_action_elapsed_s",
        None,
        "PaneAction last-event elapsed seconds",
    ),
    HeartbeatField("action_counts", {}, "per-action count map"),
    HeartbeatField(
        "sac_hooks_p95_elapsed_s_by_action", {}, "p95 latency per action name"
    ),
    HeartbeatField(
        "sac_status",
        {},
        "whole `scitex-agent-container status --terse` dict, forwarded as-is",
    ),
    HeartbeatField(
        "cron_jobs", [], "orochi-cron daemon job state for the Machines tab"
    ),
    # ---- oauth -----------------------------------------------------
    HeartbeatField("oauth_email", "", "Claude Code OAuth account email"),
    HeartbeatField("oauth_org_name", "", "Claude Code OAuth org name"),
    HeartbeatField("oauth_account_uuid", "", "Claude Code OAuth account UUID"),
    HeartbeatField("oauth_display_name", "", "Claude Code OAuth display name"),
    HeartbeatField("billing_type", "", "subscription / usage-based / free"),
    HeartbeatField(
        "has_available_subscription",
        None,
        "True/False from the OAuth introspect endpoint",
    ),
    HeartbeatField("usage_disabled_reason", "", "why usage is disabled if it is"),
    HeartbeatField("has_extra_usage_enabled", None, "True if extra-usage is opted in"),
    HeartbeatField("subscription_created_at", "", "ISO-8601 subscription start"),
    # ---- meta ------------------------------------------------------
    HeartbeatField(
        "orochi_heartbeat_schema_version",
        0,
        "wire-format schema version; see HEARTBEAT_SCHEMA_VERSION constant",
    ),
    HeartbeatField("channels", [], "channel subscription list"),
    HeartbeatField(
        "alive", True, "producer says 'I am up' (False = explicit shutdown signal)"
    ),
)

HEARTBEAT_FIELD_NAMES: frozenset[str] = frozenset(f.name for f in HEARTBEAT_FIELDS)
"""Convenience set for membership / drift tests."""
