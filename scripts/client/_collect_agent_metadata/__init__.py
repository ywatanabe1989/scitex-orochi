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
    _classify_orochi_pane_state,  # noqa: F401
    _extract_compose_text,  # noqa: F401
    _extract_stuck_prompt,  # noqa: F401
)
from ._cli import cli_main
from ._collect import collect, main
from ._hooks import _SAC_TO_HUB, _collect_hook_events  # noqa: F401
from ._hostname import _resolve_canonical_hostname  # noqa: F401
from ._metrics import collect_machine_metrics, collect_orochi_slurm_status
from ._multiplexer import _list_local_agents, detect_multiplexer  # noqa: F401
from ._oauth import read_oauth_metadata
from ._proc import _read_process_env  # noqa: F401
from ._push import _http_post_json, push_all  # noqa: F401

# Back-compat: callers that iterated _HOOK_EVENT_KEYS as a list of strings now
# get the hub-side key names (the values of the mapping).
_HOOK_EVENT_KEYS = tuple(_SAC_TO_HUB.values())

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
