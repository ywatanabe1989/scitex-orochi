"""CLI commands: scitex-orochi {launch,restart,stop,status} for agent lifecycle.

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

Phase 1d Step B additionally exposes an empty ``agent`` click group — the
noun dispatcher that will host ``agent launch/restart/status/stop/list/
fleet-list`` once Step C migrates the existing flat verbs. The group is
deliberately empty in Step B; it co-exists with the legacy flat commands.
"""

from __future__ import annotations

import click

from scitex_orochi._cli._help_availability import annotate_help_with_availability

from ._launch import agent_launch
from ._restart import agent_restart
from ._status import agent_status
from ._stop import agent_stop


# ── Phase 1d Step B: empty noun dispatcher ─────────────────────────────
# No verbs are registered under this group in Step B. Step C migrates
# the flat ``agent-launch / agent-restart / agent-stop / agent-status``
# commands and introduces ``agent list / agent fleet-list``.
@click.group(
    "agent",
    short_help="Agent lifecycle and fleet view",
    help="Agent lifecycle and fleet view (launch, restart, stop, status, list).",
)
def agent() -> None:
    """Agent-scoped verbs. Subcommands populate in Phase 1d Step C."""


annotate_help_with_availability(agent)


__all__ = [
    "agent",
    "agent_launch",
    "agent_restart",
    "agent_status",
    "agent_stop",
]
