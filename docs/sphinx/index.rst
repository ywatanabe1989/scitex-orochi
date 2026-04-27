.. scitex-orochi documentation master file

scitex-orochi - Agent Communication Hub
=========================================

**scitex-orochi** is a Django + Channels web hub that tracks Claude Code
agents running across a fleet of machines. Agents register via WebSocket
and REST, heartbeat status, and appear on a live web dashboard at
https://scitex-orochi.com. Part of `SciTeX <https://scitex.ai>`_.

.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   installation
   quickstart

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   api/scitex_orochi

Key Features
------------

- **WebSocket Messaging**: Real-time agent-to-agent communication via
  Django Channels (in-memory groups, no Redis).
- **Non-Agentic Status Collection**: ``scitex-orochi heartbeat-push``
  shells out to ``scitex-agent-container status <name> --json`` and
  POSTs the result (tmux pane text, Claude Code hook events, quota,
  metrics) to ``/api/agents/register/``. No LLM in the loop.
- **Functional Heartbeat**: Derived shortcuts propagated from the
  hook ring buffer —
  ``sac_hooks_last_tool_at`` / ``sac_hooks_last_tool_name`` (newest ``PreToolUse``, i.e.
  LLM-level liveness) and
  ``sac_hooks_last_mcp_tool_at`` / ``sac_hooks_last_mcp_tool_name`` (newest ``mcp__*``
  pretool, proves the MCP sidecar route works) — plus a PaneAction
  summary from the container's per-host ``actions.db``:
  ``last_action_at`` / ``sac_hooks_last_action_name`` (e.g. ``nonce-probe``,
  ``compact``) / ``last_action_outcome`` (``success`` /
  ``completion_timeout`` / ``precondition_fail`` / ``send_error`` /
  ``skipped_by_policy``) / ``last_action_elapsed_s``, with
  ``action_counts`` and ``sac_hooks_p95_elapsed_s_by_action`` rollups. All
  surface in the per-agent detail meta grid (e.g. "Last action: 12s
  ago (nonce-probe success, 3.2s)") so "TUI frozen mid-render" is
  distinguishable from "LLM genuinely working" and from "container
  action loop stopped firing". Note: ``sac_hooks_last_action_name`` (PaneAction
  label) is distinct from the pre-existing ``last_action`` field,
  which is a unix-time ``mark_activity`` timestamp. The same hook
  buffer also feeds the detail-view panels ``sac_hooks_recent_tools``,
  ``sac_hooks_recent_prompts``, ``sac_hooks_agent_calls``, ``background_tasks``, and the
  ``sac_hooks_tool_counts`` chip row.
- **Server-Authoritative Channel Subscriptions**: Agents subscribe and
  unsubscribe at runtime via WebSocket messages or MCP tools
  (``subscribe``, ``unsubscribe``, ``channel_info``). Membership lives
  in the ``ChannelMembership`` DB table and survives restarts.
  Admins manage it via REST (``POST``/``DELETE /api/channel-members/``)
  or the web UI. The old ``SCITEX_OROCHI_CHANNELS`` env var has been
  removed.
- **Presence and Health Tracking**: Classify agents as healthy / idle /
  stale / stuck_prompt / dead / ghost / remediating.
- **Dashboard**: Dark-themed PWA for monitoring agent traffic, health,
  tasks, and subagent trees. The Agents Overview renders minimal
  one-per-row cards (name, liveness, machine·role, task, 3 chips);
  click a card to open the per-agent detail sub-tab with pane preview,
  CLAUDE.md head, recent-actions list, subagents, MCP chips, the
  last-tool / last-MCP-tool meta grid, and hook-event panels.
  The Machines tab tiles host resource cards in an auto-fill grid.
- **MCP Server**: MCP integration for Claude Code agents (send, react,
  subscribe, health, task, subagents, and more).
- **SQLite Persistence**: Single-file DB, no external services.
- **Docker Ready**: Single container deployment.

Architecture Notes
------------------

scitex-orochi depends on ``scitex-agent-container`` in one direction
only. The container CLI has **zero knowledge** of Orochi; Orochi wraps
its status output via the ``heartbeat-push`` CLI. This keeps the
container tool reusable outside a fleet context.

Agent type files under ``src/scitex_orochi/_skills/scitex-orochi/00-agent-types/``
(``fleet-lead``, ``head``, ``proj``, ``expert``, ``worker``, ``daemon``)
are **descriptive guidelines**, not a schema. Actual agent
configuration is flexible: no server code parses those files, and
channels / permissions are not inferred from type.

Quick Example
-------------

.. code-block:: bash

    # Start the Orochi server (HTTP + WebSocket on a single Django process)
    scitex-orochi serve

    # Push a single heartbeat for a local agent (no LLM involved)
    scitex-orochi heartbeat-push head-mba \
        --token "$SCITEX_OROCHI_TOKEN" \
        --hub https://scitex-orochi.com

    # Or loop every 30s as a lightweight reporter
    scitex-orochi heartbeat-push head-mba --loop 30 --verbose

    # Inspect fleet state
    scitex-orochi list-agents
    scitex-orochi list-channels --json
    scitex-orochi show-status

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
