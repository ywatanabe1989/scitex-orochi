"""CLI commands: scitex-orochi agent {launch,restart,stop,status,list,fleet-list}.

Direct agent lifecycle management using agent definitions from
~/.scitex/orochi/agents/<name>/.  Each agent directory may contain:
  - config.yaml  (host, role, channels, etc.)
  - .mcp.json.example  (MCP config template with $HOME etc.)
  - CLAUDE.md  (agent-specific instructions)
  - <name>.yaml  (legacy agent-container spec, used for metadata)

Launch flow:
  1. Read agent definition
  2. Determine host (from config.yaml or derive from name)
  3. SSH to host (or local if localhost)
  4. Run setup-workspace.sh to prepare workspace
  5. Start screen session with claude
  6. After delay, press Enter to confirm dev channel dialog

Phase 1d Step C (plan PR #337): the nested verbs ``agent launch /
restart / stop / status / list / fleet-list`` live here. The flat
legacy commands (``agent-launch``, ``list-agents``, ``fleet``, etc.)
are stubbed in ``_main.py`` to return ``hard_rename_error``.
"""

from __future__ import annotations

import click

from scitex_orochi._cli._help_availability import annotate_help_with_availability

from ._launch import agent_launch
from ._restart import agent_restart
from ._status import agent_status
from ._stop import agent_stop


# ── Phase 1d Step C: noun dispatcher with migrated verbs ───────────────
@click.group(
    "agent",
    short_help="Agent lifecycle and fleet view",
    help="Agent lifecycle and fleet view (launch, restart, stop, status, list, fleet-list).",
)
def agent() -> None:
    """Agent-scoped verbs (Phase 1d Step C)."""


# Register the four original lifecycle verbs under short names.
# The command functions were declared with click names like
# ``agent-launch``; we re-expose them as ``launch`` etc. under the
# group by passing an explicit ``name=`` to ``add_command``.
agent.add_command(agent_launch, name="launch")
agent.add_command(agent_restart, name="restart")
agent.add_command(agent_stop, name="stop")
agent.add_command(agent_status, name="status")

# Deferred imports to avoid circular import (query_cmd / fleet_cmd
# both pull helpers that may import agent_cmd transitively).


def _register_list_and_fleet() -> None:
    from scitex_orochi._cli.commands.fleet_cmd import fleet
    from scitex_orochi._cli.commands.query_cmd import list_agents

    agent.add_command(list_agents, name="list")
    agent.add_command(fleet, name="fleet-list")


_register_list_and_fleet()

annotate_help_with_availability(agent)


__all__ = [
    "agent",
    "agent_launch",
    "agent_restart",
    "agent_status",
    "agent_stop",
]
