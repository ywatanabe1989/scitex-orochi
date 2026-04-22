"""``scitex-orochi mcp`` — explicit flat keeper group for MCP glue.

Phase 1d Step A (plan PR #337, Q5 decision): the **only** approved flat
keeper beyond the global flags is ``mcp start``. It preserves its shape
because external MCP-client configs (Claude Desktop / Claude Code
mcp.json entries) reference this exact path literal, and breaking that
contract would invalidate every deployed config overnight.

The actual stdio server lives in :mod:`scitex_orochi.mcp_server` and is
wired to the ``scitex-orochi-mcp`` entry-point in ``pyproject.toml``.
Step A only adds the CLI-side alias so operators can say ``scitex-orochi
mcp start`` without installing a second console script.

The real implementation lands in Step B — this stub intentionally
short-circuits into ``scitex_orochi.mcp_server.main`` with no extra flag
handling.
"""
# TODO: wire in Step B — currently this re-uses scitex-orochi-mcp
# entry-point as-is. Step B will add ``mcp start --config`` and
# ``mcp status`` siblings, and this module will grow accordingly.

from __future__ import annotations

import click


@click.group(help="MCP (Model Context Protocol) integration.")
def mcp() -> None:
    """Group for MCP-related verbs. Only ``start`` is implemented in Step A."""


@mcp.command("start", help="Start the stdio MCP server (same as scitex-orochi-mcp).")
def mcp_start() -> None:
    """Delegate to the canonical MCP entry-point.

    Importing ``scitex_orochi.mcp_server`` runs its module-level safety
    guards (SCITEX_OROCHI_DISABLE checks, env sanity), so we preserve
    that behaviour by calling its ``main()`` directly rather than
    re-implementing the glue here.
    """
    from scitex_orochi.mcp_server import main as _mcp_main

    _mcp_main()
