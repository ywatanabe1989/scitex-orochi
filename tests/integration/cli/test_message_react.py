"""Tests for ``scitex-orochi message react {add,remove}`` (msg#16489).

Covers:

* Group registration: ``react`` exists under the ``message`` noun group
  with ``add`` and ``remove`` sub-verbs.
* Happy path: both verbs POST/DELETE the correct URL + JSON body,
  surface the hub's ``action`` field in human + JSON output.
* Auth: missing token → exit !=0 with a helpful message.
* Error propagation: 401/404/500 → exit 1, hub body surfaced.
* ``--json`` top-level flag flows through to the sub-verb.
* Unicode emoji passes through the body round-trip (``ensure_ascii=False``
  in the JSON output, UTF-8 on the wire).

No live network — ``_http_json`` is monkeypatched.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from scitex_orochi._cli._main import orochi
from scitex_orochi._cli.commands import _message_react_cmd as mr

# ---------------------------------------------------------------------------
# Group registration
# ---------------------------------------------------------------------------


def test_react_group_registered_under_message() -> None:
    """``message react`` is a click.Group with ``add`` and ``remove``."""
    message = orochi.commands["message"]
    assert "react" in message.commands  # type: ignore[attr-defined]
    react = message.commands["react"]  # type: ignore[attr-defined]
    assert set(react.commands.keys()) == {"add", "remove"}


def test_message_help_mentions_react() -> None:
    """``scitex-orochi message --help`` advertises the new ``react`` verb."""
    runner = CliRunner()
    result = runner.invoke(
        orochi, ["message", "--help"], obj={"host": "127.0.0.1", "port": 9559}
    )
    assert result.exit_code == 0
    assert "react" in result.output


def test_react_help_renders_cleanly() -> None:
    runner = CliRunner()
    result = runner.invoke(
        orochi, ["message", "react", "--help"], obj={"host": "127.0.0.1", "port": 9559}
    )
    assert result.exit_code == 0
    assert "add" in result.output
    assert "remove" in result.output
    # Help text notes the MCP tool parity
    assert "MCP" in result.output or "mcp" in result.output


# ---------------------------------------------------------------------------
# react add — happy path
# ---------------------------------------------------------------------------


def test_react_add_posts_reaction(monkeypatch: pytest.MonkeyPatch) -> None:
    """``message react add <id> <emoji>`` POSTs to /api/reactions/."""
    calls: dict = {}

    def fake_http(method, url, token, body=None, timeout=15):
        calls["method"] = method
        calls["url"] = url
        calls["token"] = token
        calls["body"] = body
        return 200, {"status": "ok", "action": "added"}

    monkeypatch.setattr(mr, "_http_json", fake_http)
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "tk-abc")
    monkeypatch.setenv("SCITEX_OROCHI_AGENT", "head-mba")

    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["message", "react", "add", "12345", "👍"],
        obj={},
    )
    assert result.exit_code == 0, result.output
    assert calls["method"] == "POST"
    assert calls["url"].endswith("/api/reactions/")
    assert calls["token"] == "tk-abc"
    assert calls["body"] == {
        "message_id": 12345,
        "emoji": "👍",
        "reactor": "head-mba",
    }
    assert "reacted" in result.output
    assert "12345" in result.output


def test_react_add_idempotent_existed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-adding an existing reaction prints the no-op notice."""
    monkeypatch.setattr(
        mr, "_http_json", lambda *a, **kw: (200, {"status": "ok", "action": "existed"})
    )
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "tk")
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["message", "react", "add", "7", "✅"],
        obj={},
    )
    assert result.exit_code == 0, result.output
    assert "already reacted" in result.output
    assert "no-op" in result.output


def test_react_add_json_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Top-level ``--json`` emits the canonical payload on stdout."""
    monkeypatch.setattr(
        mr, "_http_json", lambda *a, **kw: (200, {"status": "ok", "action": "added"})
    )
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "tk")
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["--json", "message", "react", "add", "42", "🎉"],
        obj={},
    )
    assert result.exit_code == 0, result.output
    last = result.output.strip().splitlines()[-1]
    payload = json.loads(last)
    assert payload == {
        "status": "ok",
        "msg_id": 42,
        "emoji": "🎉",
        "action": "add",
        "hub_action": "added",
    }


# ---------------------------------------------------------------------------
# react remove — happy path
# ---------------------------------------------------------------------------


def test_react_remove_deletes_reaction(monkeypatch: pytest.MonkeyPatch) -> None:
    """``message react remove`` issues DELETE with the same body shape."""
    calls: dict = {}

    def fake_http(method, url, token, body=None, timeout=15):
        calls["method"] = method
        calls["url"] = url
        calls["body"] = body
        return 200, {"status": "ok", "action": "removed"}

    monkeypatch.setattr(mr, "_http_json", fake_http)
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "tk")
    monkeypatch.setenv("SCITEX_OROCHI_AGENT", "head-nas")

    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["message", "react", "remove", "99", "🚀"],
        obj={},
    )
    assert result.exit_code == 0, result.output
    assert calls["method"] == "DELETE"
    assert calls["url"].endswith("/api/reactions/")
    assert calls["body"] == {
        "message_id": 99,
        "emoji": "🚀",
        "reactor": "head-nas",
    }
    assert "removed" in result.output
    assert "99" in result.output


def test_react_remove_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Removing a non-existent reaction prints the no-op notice (exit 0)."""
    monkeypatch.setattr(
        mr,
        "_http_json",
        lambda *a, **kw: (200, {"status": "ok", "action": "not_found"}),
    )
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "tk")
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["message", "react", "remove", "7", "✅"],
        obj={},
    )
    assert result.exit_code == 0
    assert "no ✅ reaction" in result.output
    assert "no-op" in result.output


# ---------------------------------------------------------------------------
# --workspace override is forwarded in the body
# ---------------------------------------------------------------------------


def test_workspace_override_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--workspace`` and ``$SCITEX_OROCHI_WORKSPACE`` are forwarded in the body."""
    captured: dict = {}

    def fake_http(method, url, token, body=None, timeout=15):
        captured["body"] = body
        return 200, {"status": "ok", "action": "added"}

    monkeypatch.setattr(mr, "_http_json", fake_http)
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "tk")
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        [
            "message",
            "react",
            "add",
            "1",
            "👍",
            "--workspace",
            "scitex",
        ],
        obj={},
    )
    assert result.exit_code == 0, result.output
    assert captured["body"]["workspace"] == "scitex"


def test_workspace_env_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """``$SCITEX_OROCHI_WORKSPACE`` supplies the default when flag is absent."""
    captured: dict = {}

    def fake_http(method, url, token, body=None, timeout=15):
        captured["body"] = body
        return 200, {"status": "ok", "action": "added"}

    monkeypatch.setattr(mr, "_http_json", fake_http)
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "tk")
    monkeypatch.setenv("SCITEX_OROCHI_WORKSPACE", "lab-alpha")
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["message", "react", "add", "2", "👀"],
        obj={},
    )
    assert result.exit_code == 0, result.output
    assert captured["body"]["workspace"] == "lab-alpha"


# ---------------------------------------------------------------------------
# Auth: missing token
# ---------------------------------------------------------------------------


def test_react_add_missing_token_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """No token anywhere → exit !=0 with the SCITEX_OROCHI_TOKEN hint."""
    monkeypatch.delenv("SCITEX_OROCHI_TOKEN", raising=False)
    monkeypatch.setattr(mr, "load_workspace_token", lambda: None)
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["message", "react", "add", "1", "👍"],
        obj={},
    )
    assert result.exit_code != 0
    combined = result.output + str(result.exception or "")
    assert "SCITEX_OROCHI_TOKEN" in combined


# ---------------------------------------------------------------------------
# HTTP error propagation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,body,needle",
    [
        (401, {"error": "invalid token"}, "invalid token"),
        (404, {"error": "message not found"}, "not found"),
        (500, "boom", "500"),
    ],
)
def test_react_add_http_error_exit_1(
    monkeypatch: pytest.MonkeyPatch, status: int, body, needle: str
) -> None:
    """Non-2xx → exit 1; stderr carries the hub's body."""
    monkeypatch.setattr(mr, "_http_json", lambda *a, **kw: (status, body))
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "tk")
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["message", "react", "add", "1", "👍"],
        obj={},
    )
    assert result.exit_code == 1
    assert needle in result.output or str(status) in result.output


def test_react_remove_http_error_json_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--json`` mode emits a structured error envelope and exits 1."""
    monkeypatch.setattr(
        mr, "_http_json", lambda *a, **kw: (404, {"error": "message not found"})
    )
    monkeypatch.setenv("SCITEX_OROCHI_TOKEN", "tk")
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["--json", "message", "react", "remove", "99", "👍"],
        obj={},
    )
    assert result.exit_code == 1
    last = result.output.strip().splitlines()[-1]
    payload = json.loads(last)
    assert payload["status"] == "error"
    assert payload["http"] == 404
    assert payload["action"] == "remove"
    assert payload["msg_id"] == 99
    assert payload["emoji"] == "👍"
