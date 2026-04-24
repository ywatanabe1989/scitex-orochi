"""Tests for ``scitex-orochi host-liveness probe``."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from scitex_orochi._cli._main import orochi
from scitex_orochi._cli.commands import host_liveness_cmd as hlc

MACHINES_YAML_FIXTURE = textwrap.dedent(
    """\
    machines:
      - canonical_name: mba
        hostname: mba-host
        aliases: [head-mba]
        fleet_role: {role: head}
        expected_tmux_sessions: [head-mba, healer-mba]
      - canonical_name: nas
        hostname: nas-host
        aliases: [head-nas]
        fleet_role: {role: head}
        expected_tmux_sessions: [head-nas]
    """
)


@pytest.fixture()
def yaml_path(tmp_path: Path) -> Path:
    p = tmp_path / "orochi-machines.yaml"
    p.write_text(MACHINES_YAML_FIXTURE)
    return p


def test_host_liveness_group_registered() -> None:
    assert "host-liveness" in orochi.commands
    assert "probe" in orochi.commands["host-liveness"].commands  # type: ignore[attr-defined]


def test_probe_emits_one_ndjson_per_host(
    monkeypatch: pytest.MonkeyPatch, yaml_path: Path
) -> None:
    """With a stub probe that reports TMUX_OK + expected sessions, we get
    one NDJSON row per host and exit 0."""

    def fake_probe(m, *, dry_run, connect_timeout, probe_timeout):
        return hlc.HostProbeResult(
            host=m.canonical_name,
            severity="ok",
            reachable=True,
            tmux_state="running",
            expected_agents=list(m.expected_tmux_sessions),
            alive_agents=list(m.expected_tmux_sessions),
            missing=[],
            unexpected=[],
            revive_path="none",
            actions_taken=[],
        )

    monkeypatch.setattr(hlc, "_probe_machine", fake_probe)
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        [
            "host-liveness", "probe",
            "--machines-yaml", str(yaml_path),
        ],
        obj={},
    )
    assert result.exit_code == 0, result.output
    lines = [ln for ln in result.output.splitlines() if ln.startswith("{")]
    assert len(lines) == 2
    payloads = [json.loads(ln) for ln in lines]
    hosts = [p["host"] for p in payloads]
    assert hosts == ["mba", "nas"]
    for p in payloads:
        assert p["schema"] == "scitex-orochi/host-liveness-probe/v1"
        assert p["severity"] == "ok"
        assert p["reachable"] is True
        assert p["tmux_state"] == "running"


def test_probe_yes_overrides_dry_run(
    monkeypatch: pytest.MonkeyPatch, yaml_path: Path
) -> None:
    """``--yes`` flips dry_run=False even if ``--dry-run`` is also present."""
    captured = {}

    def fake_probe(m, *, dry_run, connect_timeout, probe_timeout):
        captured["dry_run"] = dry_run
        return hlc.HostProbeResult(
            host=m.canonical_name, severity="ok", reachable=True,
            tmux_state="running",
            expected_agents=[], alive_agents=[], missing=[], unexpected=[],
            revive_path="none", actions_taken=[],
        )

    monkeypatch.setattr(hlc, "_probe_machine", fake_probe)
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        [
            "host-liveness", "probe",
            "--machines-yaml", str(yaml_path),
            "--dry-run", "--yes",
            "--host", "mba",
        ],
        obj={},
    )
    assert result.exit_code == 0, result.output
    assert captured["dry_run"] is False


def test_probe_worst_severity_is_exit_code(
    monkeypatch: pytest.MonkeyPatch, yaml_path: Path
) -> None:
    """``warn`` on one host + ``ok`` elsewhere → exit 2."""
    sev_iter = iter(["warn", "ok"])

    def fake_probe(m, *, dry_run, connect_timeout, probe_timeout):
        sev = next(sev_iter)
        return hlc.HostProbeResult(
            host=m.canonical_name, severity=sev,
            reachable=True, tmux_state="running",
            expected_agents=[], alive_agents=[], missing=[], unexpected=[],
            revive_path="none", actions_taken=[],
        )

    monkeypatch.setattr(hlc, "_probe_machine", fake_probe)
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["host-liveness", "probe", "--machines-yaml", str(yaml_path)],
        obj={},
    )
    assert result.exit_code == 2
