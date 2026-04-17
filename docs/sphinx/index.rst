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
  tasks, and subagent trees.
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
