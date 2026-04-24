"""Tests for the shared host-ops helpers (machines yaml parser, host
resolver, state/log dirs, workspace-token loader)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from scitex_orochi._cli.commands import _host_ops as hops

MACHINES_YAML_FIXTURE = textwrap.dedent(
    """\
    apiVersion: scitex-orochi/v1
    kind: FleetMachineInventory
    machines:
      - canonical_name: mba
        hostname: Yusukes-MacBook-Air.local
        aliases:
          - head-mba
          - Yusukes-MacBook-Air
        fleet_role:
          role: head
        expected_tmux_sessions:
          - head-mba
          - healer-mba
      - canonical_name: nas
        hostname: nas-box
        aliases:
          - head-nas
        fleet_role:
          role: head
        expected_tmux_sessions:
          - head-nas
      - canonical_name: offline-role
        fleet_role:
          role: specialist
    """
)


def test_parse_all_machines_shape(tmp_path: Path) -> None:
    p = tmp_path / "orochi-machines.yaml"
    p.write_text(MACHINES_YAML_FIXTURE)
    ms = hops.parse_all_machines(p)
    names = [m.canonical_name for m in ms]
    assert names == ["mba", "nas", "offline-role"]
    mba = ms[0]
    assert mba.role == "head"
    assert mba.hostname == "Yusukes-MacBook-Air.local"
    assert "head-mba" in mba.aliases
    assert "Yusukes-MacBook-Air.local" in mba.aliases  # hostname merged into aliases
    assert mba.expected_tmux_sessions == ("head-mba", "healer-mba")


def test_parse_head_machines_filters_by_role(tmp_path: Path) -> None:
    p = tmp_path / "orochi-machines.yaml"
    p.write_text(MACHINES_YAML_FIXTURE)
    heads = hops.parse_head_machines(p)
    assert [m.canonical_name for m in heads] == ["mba", "nas"]


def test_parse_missing_yaml_returns_empty(tmp_path: Path) -> None:
    assert hops.parse_all_machines(tmp_path / "no-such.yaml") == []


def test_resolve_self_host_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCITEX_OROCHI_HOSTNAME", "my-forced-host")
    assert hops.resolve_self_host() == "my-forced-host"


def test_resolve_self_host_fallback_to_socket(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SCITEX_OROCHI_HOSTNAME", raising=False)
    # Point the repo-root candidate at a directory with no resolve-hostname
    # helper so the function falls through to socket.gethostname().
    monkeypatch.setenv("SCITEX_OROCHI_REPO_ROOT", str(tmp_path))
    name = hops.resolve_self_host()
    assert name  # always non-empty
    assert "." not in name  # short form


def test_state_log_dirs_returns_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FOO_STATE_DIR", raising=False)
    monkeypatch.delenv("FOO_LOG_DIR", raising=False)
    state_dir, log_dir = hops.state_log_dirs(
        state_env="FOO_STATE_DIR",
        log_env="FOO_LOG_DIR",
    )
    assert isinstance(state_dir, Path)
    assert isinstance(log_dir, Path)
    assert "scitex" in str(state_dir)
    assert "scitex" in str(log_dir).lower()


def test_load_workspace_token_env_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "deadbeef")
    assert hops.load_workspace_token() == "deadbeef"


def test_load_workspace_token_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SCITEX_OROCHI_TOKEN", raising=False)
    # Override HOME so the dotfiles secret file is definitely absent.
    monkeypatch.setenv("HOME", str(tmp_path))
    assert hops.load_workspace_token() is None
