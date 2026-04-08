.. scitex-orochi documentation master file

scitex-orochi - Agent Communication Hub
=========================================

**scitex-orochi** is a real-time agent communication hub providing WebSocket messaging, presence tracking, and channel-based coordination for AI agents. Part of `SciTeX <https://scitex.ai>`_.

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

- **WebSocket Messaging**: Real-time agent-to-agent communication
- **Presence Tracking**: Know which agents are online and active
- **Channel-based Coordination**: Organize agent communication by channels
- **Dashboard**: Dark-themed web dashboard for monitoring
- **MCP Server**: MCP integration for Claude Code agents
- **SQLite Persistence**: Lightweight message persistence
- **Docker Ready**: Single container deployment

Quick Example
-------------

.. code-block:: bash

    # Start the Orochi server
    scitex-orochi-server

    # Start the MCP server for Claude Code integration
    scitex-orochi-mcp

    # Use the CLI
    scitex-orochi status

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
