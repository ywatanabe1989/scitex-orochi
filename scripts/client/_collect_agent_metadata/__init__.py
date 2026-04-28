"""agent_meta — Orochi per-agent metadata collector and heartbeat pusher.

Split from the original 1461-line ``scripts/client/collect_agent_metadata.py`` into
focused submodules so each file stays under the 512-line guideline.
The shim ``scripts/client/collect_agent_metadata.py`` re-exports the public API and
keeps the executable entry-point path stable for callers that hard-code
``~/.scitex/orochi/scripts/collect_agent_metadata.py`` (the bun MCP sidecar in
``ts/mcp_channel.ts`` does this).

DEPRECATED 2026-04-12: superseded by ``scitex-agent-container status
<name> --json`` for the JSON-per-agent CLI mode and by
``scitex-orochi heartbeat-push --all`` for the ``--push`` mode. Kept
temporarily as a fallback for hosts where the canonical paths haven't
been verified yet.
"""

from __future__ import annotations

from ._classifier import (
    _classify_orochi_pane_state,
    _extract_compose_text,
    _extract_stuck_prompt,
)
from ._cli import cli_main
from ._collect import collect, main
from ._hooks import _HOOK_EVENT_KEYS, _collect_hook_events
from ._hostname import _resolve_canonical_hostname
from ._metrics import collect_machine_metrics, collect_orochi_slurm_status
from ._multiplexer import _list_local_agents, detect_multiplexer
from ._oauth import read_oauth_metadata
from ._proc import _read_process_env
from ._push import _http_post_json, push_all

__all__ = [
    "cli_main",
    "collect",
    "collect_machine_metrics",
    "collect_orochi_slurm_status",
    "detect_multiplexer",
    "main",
    "push_all",
    "read_oauth_metadata",
]
