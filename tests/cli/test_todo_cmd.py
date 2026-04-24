"""Tests for ``scitex-orochi todo {list,next,triage}`` (Phase 1c msg#16477)."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from scitex_orochi._cli._main import orochi
from scitex_orochi._cli.commands import todo_cmd


def test_todo_group_registered() -> None:
    assert "todo" in orochi.commands
    td = orochi.commands["todo"]
    assert set(td.commands.keys()) == {"list", "next", "triage"}  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# todo list
# ---------------------------------------------------------------------------

def _issue(n: int, title: str, labels=(), assignees=(), updated="2026-04-01T00:00:00Z"):
    return {
        "number": n,
        "title": title,
        "labels": [{"name": lab} for lab in labels],
        "assignees": [{"login": a} for a in assignees],
        "updatedAt": updated,
    }


def test_list_human_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unfiltered ``todo list`` prints every open todo as a table."""
    issues = [
        _issue(101, "wire X", labels=["high-priority", "infrastructure"]),
        _issue(102, "fix Y", labels=["high-priority", "hub-admin"]),
    ]
    monkeypatch.setattr(todo_cmd, "_fetch_open_todos", lambda *a, **kw: issues)
    runner = CliRunner()
    result = runner.invoke(orochi, ["todo", "list"], obj={})
    assert result.exit_code == 0, result.output
    assert "101" in result.output and "wire X" in result.output
    assert "102" in result.output and "fix Y" in result.output


def test_list_lane_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--lane` filters by exact label match."""
    issues = [
        _issue(101, "wire X", labels=["high-priority", "infrastructure"]),
        _issue(102, "fix Y", labels=["high-priority", "hub-admin"]),
    ]
    monkeypatch.setattr(todo_cmd, "_fetch_open_todos", lambda *a, **kw: issues)
    runner = CliRunner()
    result = runner.invoke(
        orochi, ["todo", "list", "--lane", "hub-admin"], obj={}
    )
    assert result.exit_code == 0
    assert "102" in result.output
    assert "101" not in result.output


def test_list_json_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--json` returns the slim array shape."""
    issues = [_issue(101, "wire X", labels=["high-priority", "infrastructure"])]
    monkeypatch.setattr(todo_cmd, "_fetch_open_todos", lambda *a, **kw: issues)
    runner = CliRunner()
    result = runner.invoke(orochi, ["--json", "todo", "list"], obj={})
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    assert payload[0]["number"] == 101
    assert "infrastructure" in payload[0]["labels"]


# ---------------------------------------------------------------------------
# todo next
# ---------------------------------------------------------------------------

def test_next_picks_unclaimed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Picks first unclaimed lane-matching issue."""
    issues = [
        _issue(201, "already claimed", labels=["high-priority", "infrastructure"]),
        _issue(202, "fresh pick", labels=["high-priority", "infrastructure"]),
    ]
    # open PR claims todo 201 via "closes #201" in body
    prs = [{"title": "feat: x", "body": "closes #201"}]
    monkeypatch.setattr(todo_cmd, "_fetch_open_todos", lambda *a, **kw: issues)
    monkeypatch.setattr(todo_cmd, "_fetch_open_prs", lambda *a, **kw: prs)
    runner = CliRunner()
    result = runner.invoke(
        orochi, ["--json", "todo", "next", "--lane", "infrastructure"], obj={}
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["number"] == 202
    assert "lane=infrastructure" in payload["reason"]


def test_next_exits_1_when_nothing_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty lane → exit 1 with ``null`` on stdout when --json."""
    monkeypatch.setattr(todo_cmd, "_fetch_open_todos", lambda *a, **kw: [])
    monkeypatch.setattr(todo_cmd, "_fetch_open_prs", lambda *a, **kw: [])
    runner = CliRunner()
    result = runner.invoke(
        orochi, ["--json", "todo", "next", "--lane", "infrastructure"], obj={}
    )
    assert result.exit_code == 1
    assert "null" in result.output


def test_next_requires_lane() -> None:
    """``--lane`` is a required option."""
    runner = CliRunner()
    result = runner.invoke(orochi, ["todo", "next"], obj={})
    # Click click.UsageError → exit code 2
    assert result.exit_code != 0
    assert "lane" in (result.output + (str(result.exception or "")))


def test_next_respects_exclude(monkeypatch: pytest.MonkeyPatch) -> None:
    """--exclude list skips the named issue numbers."""
    issues = [
        _issue(301, "first", labels=["high-priority", "infrastructure"]),
        _issue(302, "second", labels=["high-priority", "infrastructure"]),
    ]
    monkeypatch.setattr(todo_cmd, "_fetch_open_todos", lambda *a, **kw: issues)
    monkeypatch.setattr(todo_cmd, "_fetch_open_prs", lambda *a, **kw: [])
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["--json", "todo", "next", "--lane", "infrastructure", "--exclude", "301"],
        obj={},
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["number"] == 302


# ---------------------------------------------------------------------------
# todo triage
# ---------------------------------------------------------------------------

def test_triage_json_ranked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Triage output is a list sorted by score desc."""
    issues = [
        _issue(401, "ready", labels=["high-priority", "infrastructure"]),
        _issue(402, "assigned", labels=["high-priority", "infrastructure"],
               assignees=["alice"]),
    ]
    monkeypatch.setattr(todo_cmd, "_fetch_open_todos", lambda *a, **kw: issues)
    monkeypatch.setattr(todo_cmd, "_fetch_open_prs", lambda *a, **kw: [])
    runner = CliRunner()
    result = runner.invoke(
        orochi, ["--json", "todo", "triage", "--lane", "infrastructure"], obj={}
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    # ready must rank above assigned (higher score — unassigned + unclaimed)
    assert payload[0]["number"] == 401
    assert payload[0]["score"] >= payload[1]["score"]
    # each row has score_reason + claimed_by_pr fields
    assert "score_reason" in payload[0]
    assert payload[0]["claimed_by_pr"] is False


def test_triage_lane_fit_weighs_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lane-matching issues outrank non-lane issues when --lane given."""
    issues = [
        _issue(501, "off-lane", labels=["high-priority", "specialized-domain"]),
        _issue(502, "in-lane", labels=["high-priority", "infrastructure"]),
    ]
    monkeypatch.setattr(todo_cmd, "_fetch_open_todos", lambda *a, **kw: issues)
    monkeypatch.setattr(todo_cmd, "_fetch_open_prs", lambda *a, **kw: [])
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["--json", "todo", "triage", "--lane", "infrastructure"],
        obj={},
    )
    payload = json.loads(result.output)
    # top row must be the lane-matching one
    assert payload[0]["number"] == 502


def test_triage_without_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    """No --lane → lane_fit is neutral; output still ordered by score."""
    issues = [_issue(601, "x", labels=["high-priority"])]
    monkeypatch.setattr(todo_cmd, "_fetch_open_todos", lambda *a, **kw: issues)
    monkeypatch.setattr(todo_cmd, "_fetch_open_prs", lambda *a, **kw: [])
    runner = CliRunner()
    result = runner.invoke(orochi, ["--json", "todo", "triage"], obj={})
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload[0]["number"] == 601
