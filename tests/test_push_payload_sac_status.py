"""Pin the heartbeat wire-payload contract for ``sac_status`` (msg#16005).

The pusher must attach the FULL ``scitex-agent-container status
--terse --json`` dict as a nested ``sac_status`` key on the payload
so future additions to sac's terse projection flow through the
hub unchanged. A backwards-compat ``orochi_subagent_count`` top-level
field is still emitted alongside — see the in-file comment in
``_push._build_payload``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Agent package lives under scripts/client/ — add to sys.path so the
# test can import it without pip-installing.
_AGENT_META_DIR = Path(__file__).resolve().parents[1] / "scripts" / "client"
if str(_AGENT_META_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_META_DIR))

from _collect_agent_metadata._push import _build_payload  # noqa: E402

_MIN_META = {
    "agent": "worker-mba",
    "orochi_machine": "mba",
    "orochi_subagent_count": 2,
    # Typical collect() keys — fill enough that _build_payload
    # doesn't KeyError.
    "orochi_skills_loaded": [],
    "orochi_mcp_servers": [],
    "recent_actions": [],
    "sac_hooks_recent_tools": [],
    "sac_hooks_recent_prompts": [],
    "sac_hooks_agent_calls": [],
    "sac_hooks_background_tasks": [],
    "orochi_subagents": [],
    "sac_hooks_tool_counts": {},
    "sac_hooks_p95_elapsed_s_by_action": {},
    "orochi_metrics": {},
    "orochi_slurm": None,
}


def test_sac_status_is_forwarded_verbatim():
    sac = {
        "agent": "worker-mba",
        "state": "running",
        "context_management.percent": 42.0,
        "context_management.strategy": "compact",
        "pids.claude_code": 12345,
        "health.ok": True,
    }
    payload = _build_payload(_MIN_META, "wks_token", sac_status=sac)
    assert payload["sac_status"] == sac
    # Every sac_status.<field> should be reachable by nested lookup
    # (that's the whole point of the pivot).
    assert payload["sac_status"]["context_management.percent"] == 42.0
    assert payload["sac_status"]["health.ok"] is True


def test_sac_status_empty_dict_when_cli_missing():
    # collect_sac_status returns {} on CLI-missing — the pusher must
    # forward that unchanged (not drop the key, not substitute None).
    payload = _build_payload(_MIN_META, "wks_token", sac_status={})
    assert payload["sac_status"] == {}


def test_sac_status_defaults_to_empty_when_unset():
    # Legacy call signature (pre-pivot code). Must not KeyError and
    # must still emit sac_status as an empty dict.
    payload = _build_payload(_MIN_META, "wks_token")
    assert payload["sac_status"] == {}


def test_backcompat_orochi_subagent_count_still_top_level():
    # The pivot spec explicitly keeps orochi_subagent_count at the top
    # level for backwards compat (multiple consumers key off it).
    sac = {"agent": "worker-mba"}
    payload = _build_payload(_MIN_META, "wks_token", sac_status=sac)
    assert payload["orochi_subagent_count"] == 2
