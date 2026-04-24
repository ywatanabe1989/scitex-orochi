"""Tests for ``scitex-orochi dispatch {run,status}`` (Phase 1c msg#16477)."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from scitex_orochi._cli._main import orochi
from scitex_orochi._cli.commands import dispatch_cmd as dc


def test_dispatch_group_registered() -> None:
    assert "dispatch" in orochi.commands
    d = orochi.commands["dispatch"]
    assert set(d.commands.keys()) == {"run", "status"}  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# dispatch run
# ---------------------------------------------------------------------------

def test_run_requires_head(monkeypatch: pytest.MonkeyPatch) -> None:
    """``dispatch run`` without ``--head`` fails fast."""
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "tk")
    runner = CliRunner()
    result = runner.invoke(orochi, ["dispatch", "run"], obj={})
    assert result.exit_code != 0
    assert "head" in (result.output + str(result.exception or ""))


def test_run_posts_to_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    """`dispatch run` POSTs to /api/auto-dispatch/fire/ and prints the response."""
    calls: dict = {}

    def fake_http(method, url, token, body=None, timeout=15):
        calls["method"] = method
        calls["url"] = url
        calls["token"] = token
        calls["body"] = body
        return 200, {
            "status": "ok",
            "decision": "fired",
            "agent": "head-mba",
            "lane": "infrastructure",
            "pick": {"number": 777, "title": "hello"},
            "message_id": 42,
        }

    monkeypatch.setattr(dc, "_http_json", fake_http)
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "tk")
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["dispatch", "run", "--head", "mba", "--todo", "777"],
        obj={},
    )
    assert result.exit_code == 0, result.output
    assert calls["method"] == "POST"
    assert calls["url"].endswith("/api/auto-dispatch/fire/")
    assert calls["body"] == {
        "head": "mba",
        "reason": "operator-manual",
        "todo": 777,
    }
    assert "decision:   fired" in result.output
    assert "#777" in result.output


def test_run_json_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--json` emits the hub payload verbatim on stdout."""
    def fake_http(method, url, token, body=None, timeout=15):
        return 200, {"status": "ok", "decision": "fired", "message_id": 1}

    monkeypatch.setattr(dc, "_http_json", fake_http)
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "tk")
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["--json", "dispatch", "run", "--head", "nas"],
        obj={},
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["decision"] == "fired"


def test_run_propagates_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-2xx → exit 1 with the body surfaced."""
    def fake_http(method, url, token, body=None, timeout=15):
        return 404, {"error": "agent head-nope not in registry"}

    monkeypatch.setattr(dc, "_http_json", fake_http)
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "tk")
    runner = CliRunner()
    result = runner.invoke(
        orochi, ["dispatch", "run", "--head", "nope"], obj={}
    )
    assert result.exit_code == 1
    assert "404" in result.output or "not in registry" in result.output


def test_run_missing_token_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """No token anywhere → ClickException."""
    monkeypatch.delenv("SCITEX_OROCHI_TOKEN", raising=False)
    monkeypatch.setattr(dc, "load_workspace_token", lambda: None)
    runner = CliRunner()
    result = runner.invoke(
        orochi, ["dispatch", "run", "--head", "mba"], obj={}
    )
    assert result.exit_code != 0
    assert "SCITEX_OROCHI_TOKEN" in (result.output + str(result.exception or ""))


# ---------------------------------------------------------------------------
# dispatch status
# ---------------------------------------------------------------------------

def test_status_human(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default output prints a table with one row per head."""
    rows = [
        {
            "agent": "head-mba",
            "host": "mba",
            "lane": "infrastructure",
            "idle_streak": 1,
            "subagent_count": 0,
            "last_fire_ts": None,
            "last_fire_at": None,
            "cooldown_active": False,
            "cooldown_remaining_s": 0,
            "streak_threshold": 2,
            "cooldown_seconds": 900,
        },
        {
            "agent": "head-nas",
            "host": "nas",
            "lane": "hub-admin",
            "idle_streak": 0,
            "subagent_count": 3,
            "last_fire_ts": 1_700_000_000.0,
            "last_fire_at": "2023-11-14T22:13:20+00:00",
            "cooldown_active": True,
            "cooldown_remaining_s": 300,
            "streak_threshold": 2,
            "cooldown_seconds": 900,
        },
    ]

    monkeypatch.setattr(dc, "_http_json", lambda *a, **kw: (200, rows))
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "tk")
    runner = CliRunner()
    result = runner.invoke(orochi, ["dispatch", "status"], obj={})
    assert result.exit_code == 0, result.output
    assert "head-mba" in result.output
    assert "head-nas" in result.output
    # cooldown_remaining rendered as "300s" on the nas row
    assert "300s" in result.output


def test_status_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--json` emits the array verbatim."""
    rows = [{"agent": "head-mba", "idle_streak": 0, "subagent_count": 1}]
    monkeypatch.setattr(dc, "_http_json", lambda *a, **kw: (200, rows))
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "tk")
    runner = CliRunner()
    result = runner.invoke(orochi, ["--json", "dispatch", "status"], obj={})
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert isinstance(payload, list)
    assert payload[0]["agent"] == "head-mba"


def test_status_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty list prints the human-friendly no-heads notice."""
    monkeypatch.setattr(dc, "_http_json", lambda *a, **kw: (200, []))
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "tk")
    runner = CliRunner()
    result = runner.invoke(orochi, ["dispatch", "status"], obj={})
    assert result.exit_code == 0
    assert "no head-*" in result.output
