#!/usr/bin/env -S python3 -u
"""Extract claude-hud-like metadata for an Orochi agent.

DEPRECATED 2026-04-12: superseded by ``scitex-agent-container status
<name> --json`` (canonical JSON-per-agent source) and
``scitex-orochi heartbeat-push --all`` (canonical heartbeat pusher).

This thin shim is kept so callers that hard-code
``~/.scitex/orochi/scripts/agent_meta.py`` (the bun MCP sidecar in
``ts/mcp_channel.ts``) keep working. The real implementation lives in
the sibling ``agent_meta_pkg/`` package and was split out 2026-04-20
because the previous monolithic 1461-line file exceeded the 512-line
guideline.

Usage:
    agent_meta.py <agent_name>
        Print JSON metadata for one agent to stdout (legacy behavior).

    agent_meta.py --push [--url URL] [--token TOKEN]
        Enumerate all local tmux/screen agent sessions, collect metadata
        for each, and POST each entry to the Orochi hub's
        /api/agents/register/ heartbeat endpoint.

        URL defaults to $SCITEX_OROCHI_URL_HTTP, else https://scitex-orochi.com
        TOKEN defaults to $SCITEX_OROCHI_TOKEN (workspace token).

        Skipped entirely if $SCITEX_OROCHI_REGISTRY_DISABLE=1.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the sibling ``agent_meta_pkg/`` package is importable regardless
# of how this shim is invoked (direct path execution, ``python -m`` from
# elsewhere, symlink under ~/.scitex/orochi/scripts/, etc.).
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from agent_meta_pkg import (  # noqa: E402  (sys.path adjusted above)
    collect,
    collect_machine_metrics,
    collect_slurm_status,
    detect_multiplexer,
    main,
    push_all,
    read_oauth_metadata,
)
from agent_meta_pkg._cli import cli_main  # noqa: E402

__all__ = [
    "collect",
    "collect_machine_metrics",
    "collect_slurm_status",
    "detect_multiplexer",
    "main",
    "push_all",
    "read_oauth_metadata",
]


if __name__ == "__main__":
    sys.exit(cli_main())
