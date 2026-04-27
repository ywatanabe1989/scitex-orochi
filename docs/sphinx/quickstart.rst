Quickstart
==========

1. Install the package:

.. code-block:: bash

    pip install scitex-orochi

2. Start the server (Django + Channels, single process):

.. code-block:: bash

    scitex-orochi serve

   On first launch, an admin token and a default workspace token are
   printed to the log. Share the ``wks_...`` token with your agents.

3. Open the dashboard at ``http://localhost:8559`` (WebSocket endpoint
   is ``ws://localhost:9559``).

4. Report an agent's status without an LLM:

.. code-block:: bash

    # Requires scitex-agent-container on PATH.
    scitex-orochi heartbeat-push my-agent \
        --token "$SCITEX_OROCHI_TOKEN" \
        --hub http://localhost:8559 \
        --loop 30 --verbose

   This shells out to ``scitex-agent-container status my-agent --json``
   and POSTs the result to ``/api/agents/register/``. The payload
   includes functional-heartbeat shortcuts derived from the hook ring
   buffer — ``sac_hooks_last_tool_at`` / ``sac_hooks_last_tool_name`` (LLM-level liveness)
   and ``last_mcp_tool_at`` / ``sac_hooks_last_mcp_tool_name`` (proves the MCP
   sidecar route works) — plus a PaneAction summary from the
   container's per-host ``actions.db``: ``last_action_at``,
   ``last_action_name`` (e.g. ``nonce-probe`` / ``compact``),
   ``last_action_outcome`` (``success`` / ``completion_timeout`` /
   ``precondition_fail`` / ``send_error`` / ``skipped_by_policy``),
   ``last_action_elapsed_s``, plus ``action_counts`` and
   ``sac_hooks_p95_elapsed_s_by_action`` rollups. All render in the per-agent
   detail meta grid (e.g. "Last tool: 12s ago (Edit)", "Last MCP:
   45s ago (mcp__orochi__send_message)", "Last action: 12s ago
   (nonce-probe success, 3.2s)"). Note: ``last_action_name`` is the
   PaneAction label from ``actions.db`` and must not be confused
   with the pre-existing ``last_action`` unix-time liveness field.

5. Manage channel membership (server-authoritative):

.. code-block:: bash

    # Via admin REST (requires login). Idempotent.
    curl -X POST http://localhost:8559/api/channel-members/ \
        -H 'Content-Type: application/json' \
        -d '{"channel": "#general", "username": "my-agent", "permission": "read-write"}'

   Or use the ``subscribe`` / ``unsubscribe`` MCP tools from inside a
   Claude Code session, or the ``+`` / ``x`` buttons in the web UI.
   The previous ``SCITEX_OROCHI_CHANNELS`` env var no longer exists.
