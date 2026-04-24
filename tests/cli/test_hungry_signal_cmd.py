"""Unit tests for the Python ``scitex-orochi hungry-signal check`` command.

The existing integration test ``tests/test_hungry_signal_counter.py``
exercises the end-to-end shell wrapper; here we drive the Click command
directly so we can cover the skip / kill-switch paths without shelling
out.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from scitex_orochi._cli._main import orochi
from scitex_orochi._cli.commands import hungry_signal_cmd as hsc

MACHINES_YAML_FIXTURE = textwrap.dedent(
    """\
    machines:
      - canonical_name: mba
        fleet_role: {role: head}
      - canonical_name: nas
        fleet_role: {role: head}
    """
)


@pytest.fixture()
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    yaml_path = tmp_path / "orochi-machines.yaml"
    yaml_path.write_text(MACHINES_YAML_FIXTURE)
    monkeypatch.setenv("SCITEX_OROCHI_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("SCITEX_OROCHI_HOSTNAME", "mba")
    monkeypatch.setenv("HUNGRY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("HUNGRY_LOG_DIR", str(tmp_path / "log"))
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "")
    monkeypatch.delenv("SCITEX_HUNGRY_DISABLED", raising=False)
    return tmp_path


def test_hungry_signal_registered() -> None:
    assert "hungry-signal" in orochi.commands
    assert "check" in orochi.commands["hungry-signal"].commands  # type: ignore[attr-defined]


def test_kill_switch_exits_silently(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SCITEX_HUNGRY_DISABLED", "1")
    runner = CliRunner()
    result = runner.invoke(orochi, ["hungry-signal", "check"], obj={})
    assert result.exit_code == 0
    assert result.output.strip() == ""


def test_non_head_host_is_noop(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--host orphan`` is not a head → benign exit 0."""
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["hungry-signal", "check", "--host", "orphan"],
        obj={},
    )
    assert result.exit_code == 0
    assert result.output.strip() == ""


def test_zero_reading_counts_and_emits_ndjson(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """subagent_count=0 + threshold=2 → decision=counting, exit 0."""
    monkeypatch.setattr(hsc, "_read_from_sac", lambda a: (0, ["head-mba"]))
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["hungry-signal", "check", "--yes", "--threshold", "2"],
        obj={},
    )
    assert result.exit_code == 0
    lines = [ln for ln in result.output.splitlines() if ln.startswith("{")]
    assert lines, result.output
    obj = json.loads(lines[-1])
    assert obj["schema"] == "scitex-orochi/hungry-signal/v1"
    assert obj["decision"] == "counting"
    assert obj["consecutive_zero_cycles"] == 1
    assert obj["fired"] is False
    assert obj["lane"] == "infrastructure"


def test_subagent_count_missing_exit_2(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No sac, no hub → decision=skip, exit 2."""
    monkeypatch.setattr(hsc, "_read_from_sac", lambda a: (None, []))
    monkeypatch.setattr(hsc, "_read_from_hub", lambda a, h, t: (None, []))
    runner = CliRunner()
    result = runner.invoke(orochi, ["hungry-signal", "check"], obj={})
    assert result.exit_code == 2
    obj = json.loads(result.output.strip().splitlines()[-1])
    assert obj["decision"] == "skip"
    assert obj["reason"] == "no_subagent_count_source"


def test_yes_overrides_dry_run(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--yes`` must write to the state file, ``--dry-run`` must not."""
    monkeypatch.setattr(hsc, "_read_from_sac", lambda a: (0, []))
    state_file = fake_repo / "state" / "hungry-signal.state"
    runner = CliRunner()
    # dry-run → no state.
    result_dry = runner.invoke(orochi, ["hungry-signal", "check"], obj={})
    assert result_dry.exit_code == 0
    assert not state_file.exists() or state_file.read_text().strip() == ""

    # --dry-run --yes → --yes wins → state file appears.
    result_yes = runner.invoke(
        orochi,
        ["hungry-signal", "check", "--dry-run", "--yes"],
        obj={},
    )
    assert result_yes.exit_code == 0
    assert state_file.exists()
    assert "mba" in state_file.read_text()
