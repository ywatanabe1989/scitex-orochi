"""Unit tests for ``agent_meta_pkg._sac_status.collect_sac_status``.

Pins the lead msg#16005 pivot contract: the heartbeat pusher shells
out to ``scitex-agent-container status <name> --terse --json`` and
attaches the parsed dict verbatim to the heartbeat payload. The
helper must fail soft on every failure mode (CLI missing, nonzero
exit, bad JSON, timeout) so a sac glitch never breaks the heartbeat
loop.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

# The agent_meta_pkg package lives under scripts/client/ and isn't
# installed into site-packages — make it importable for this test.
_AGENT_META_DIR = Path(__file__).resolve().parents[1] / "scripts" / "client"
if str(_AGENT_META_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_META_DIR))

from agent_meta_pkg import _sac_status  # noqa: E402
from agent_meta_pkg._sac_status import collect_sac_status  # noqa: E402


def _fake_completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    """Build a subprocess.CompletedProcess stub."""
    return subprocess.CompletedProcess(
        args=["scitex-agent-container", "status"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_returns_parsed_dict_on_success():
    fake_json = {
        "agent": "worker-mba",
        "state": "running",
        "context_management.percent": 42.0,
        "pids.claude_code": 12345,
    }
    with mock.patch.object(_sac_status.shutil, "which", return_value="/bin/sac"), mock.patch.object(
        _sac_status.subprocess, "run", return_value=_fake_completed(stdout=json.dumps(fake_json))
    ) as _run:
        out = collect_sac_status("worker-mba")
    assert out == fake_json
    # Verify we actually invoked --terse --json.
    args, _kwargs = _run.call_args
    cmd = args[0]
    assert "--terse" in cmd and "--json" in cmd
    assert "worker-mba" in cmd


def test_empty_agent_name_short_circuits():
    # No subprocess call should happen.
    with mock.patch.object(_sac_status.subprocess, "run") as _run:
        assert collect_sac_status("") == {}
    _run.assert_not_called()


def test_cli_missing_returns_empty_dict():
    with mock.patch.object(_sac_status.shutil, "which", return_value=None), mock.patch.object(
        _sac_status.subprocess, "run"
    ) as _run:
        assert collect_sac_status("worker-mba") == {}
    _run.assert_not_called()


def test_nonzero_exit_returns_empty_dict():
    with mock.patch.object(_sac_status.shutil, "which", return_value="/bin/sac"), mock.patch.object(
        _sac_status.subprocess,
        "run",
        return_value=_fake_completed(returncode=1, stderr="agent not found"),
    ):
        assert collect_sac_status("nonexistent") == {}


def test_invalid_json_returns_empty_dict():
    with mock.patch.object(_sac_status.shutil, "which", return_value="/bin/sac"), mock.patch.object(
        _sac_status.subprocess,
        "run",
        return_value=_fake_completed(stdout="not valid json { "),
    ):
        assert collect_sac_status("worker-mba") == {}


def test_non_dict_json_returns_empty_dict():
    with mock.patch.object(_sac_status.shutil, "which", return_value="/bin/sac"), mock.patch.object(
        _sac_status.subprocess,
        "run",
        return_value=_fake_completed(stdout="[1, 2, 3]"),
    ):
        assert collect_sac_status("worker-mba") == {}


def test_timeout_returns_empty_dict():
    def _raise_timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="sac", timeout=3.0)

    with mock.patch.object(_sac_status.shutil, "which", return_value="/bin/sac"), mock.patch.object(
        _sac_status.subprocess, "run", side_effect=_raise_timeout
    ):
        assert collect_sac_status("worker-mba") == {}


def test_unexpected_exception_returns_empty_dict():
    def _raise(*_a, **_k):
        raise OSError("permission denied")

    with mock.patch.object(_sac_status.shutil, "which", return_value="/bin/sac"), mock.patch.object(
        _sac_status.subprocess, "run", side_effect=_raise
    ):
        assert collect_sac_status("worker-mba") == {}
