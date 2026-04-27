"""Tests for ``scitex-orochi orochi_machine heartbeat {send,status}``."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from scitex_orochi._cli._main import orochi


def test_machine_group_registered() -> None:
    assert "orochi_machine" in orochi.commands
    machine_cmd = orochi.commands["orochi_machine"]
    assert "heartbeat" in machine_cmd.commands  # type: ignore[attr-defined]
    hb = machine_cmd.commands["heartbeat"]  # type: ignore[attr-defined]
    assert set(hb.commands.keys()) == {"send", "status"}


def test_heartbeat_send_invokes_push_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """Command delegates to ``_collect_agent_metadata.push_all`` and prints the count."""
    from scitex_orochi._cli.commands import machine_cmd

    called_with = {}

    def fake_push_all(url=None, token=None):
        called_with["url"] = url
        called_with["token"] = token
        return 3

    monkeypatch.setattr(
        machine_cmd,
        "_import__collect_agent_metadata",
        lambda: (fake_push_all, lambda name: {}),
    )

    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["orochi_machine", "heartbeat", "send", "--token", "tk"],
        obj={},
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.splitlines()[-1])
    assert payload == {"pushed": 3}
    assert called_with["token"] == "tk"


def test_heartbeat_status_missing_token_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No token anywhere → ClickException exit 1."""
    monkeypatch.delenv("SCITEX_OROCHI_TOKEN", raising=False)
    from scitex_orochi._cli.commands import _host_ops

    monkeypatch.setattr(_host_ops, "load_workspace_token", lambda: None)
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["orochi_machine", "heartbeat", "status"],
        obj={},
    )
    assert result.exit_code != 0
    assert "no SCITEX_OROCHI_TOKEN" in (result.output + str(result.exception))


def test_heartbeat_status_not_found_exits_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Agent not present in hub registry → exit 1 + JSON envelope."""
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "tk")

    class _FakeResp:
        status = 200
        def __enter__(self):  # noqa: D401
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return b"[]"

    from scitex_orochi._cli.commands import machine_cmd

    def fake_urlopen(req, timeout=10):
        return _FakeResp()

    monkeypatch.setattr(machine_cmd._urllib_request, "urlopen", fake_urlopen)
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["orochi_machine", "heartbeat", "status", "--agent", "head-nope"],
        obj={},
    )
    assert result.exit_code == 1
    envelope = json.loads(result.output.splitlines()[-1])
    assert envelope["agent"] == "head-nope"
    assert envelope["found"] is False
