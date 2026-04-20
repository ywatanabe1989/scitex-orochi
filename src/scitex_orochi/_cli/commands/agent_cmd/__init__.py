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
"""

from __future__ import annotations

from ._launch import agent_launch
from ._restart import agent_restart
from ._status import agent_status
from ._stop import agent_stop

__all__ = ["agent_launch", "agent_restart", "agent_status", "agent_stop"]
