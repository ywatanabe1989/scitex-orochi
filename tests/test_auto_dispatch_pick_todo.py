"""Unit tests for scripts/client/auto-dispatch-pick-todo.py (todo: auto-dispatch daemon).

Seeded list + already-claimed filter, as called out in the spec (lead
``#heads msg#15975``). The helper's CLI layer shells out to ``gh``; these
tests exercise only the pure-function core so CI can run without network.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER = REPO_ROOT / "scripts" / "client" / "auto-dispatch-pick-todo.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("auto_dispatch_pick_todo", HELPER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


pick_mod = _load_module()


# -----------------------------------------------------------------------------
# _extract_issue_refs
# -----------------------------------------------------------------------------


def test_extract_issue_refs_handles_common_shapes():
    cases = {
        "fixes #123": {123},
        "todo#45 and also #46": {45, 46},
        "(ref: #1) [#2] #3": {1, 2, 3},
        "v2.0 release — no refs here": set(),
        "": set(),
    }
    for text, expected in cases.items():
        got = pick_mod._extract_issue_refs(text)
        assert got == expected, f"text={text!r} got={got} expected={expected}"


# -----------------------------------------------------------------------------
# claimed_numbers_from_prs
# -----------------------------------------------------------------------------


def test_claimed_numbers_from_prs_collects_title_and_body():
    prs = [
        {"title": "fix(scope): thing (#123)", "body": "also closes #124"},
        {"title": "no refs here", "body": ""},
        {"title": "chore: drop stale flag", "body": "refs todo#300"},
    ]
    assert pick_mod.claimed_numbers_from_prs(prs) == {123, 124, 300}


def test_claimed_numbers_from_prs_empty_ok():
    assert pick_mod.claimed_numbers_from_prs([]) == set()
    assert pick_mod.claimed_numbers_from_prs(None) == set()  # type: ignore[arg-type]


# -----------------------------------------------------------------------------
# pick_todo
# -----------------------------------------------------------------------------


def _issue(num, *labels, assignees=()):
    return {
        "number": num,
        "title": f"feat: thing {num}",
        "labels": [{"name": lab} for lab in labels],
        "assignees": list(assignees),
    }


def test_pick_todo_returns_first_matching_lane():
    issues = [
        _issue(100, "high-priority", "infrastructure"),
        _issue(101, "high-priority", "scitex-cloud"),
        _issue(102, "high-priority", "infrastructure"),
    ]
    got = pick_mod.pick_todo(issues, open_prs=[], lane="infrastructure")
    assert got is not None
    assert got["number"] == 100


def test_pick_todo_skips_claimed_by_open_pr():
    issues = [
        _issue(200, "high-priority", "infrastructure"),
        _issue(201, "high-priority", "infrastructure"),
    ]
    open_prs = [{"title": "wip: #200", "body": ""}]
    got = pick_mod.pick_todo(issues, open_prs, lane="infrastructure")
    assert got is not None
    assert got["number"] == 201


def test_pick_todo_skips_extra_exclude_cooldown():
    issues = [
        _issue(300, "high-priority", "infrastructure"),
        _issue(301, "high-priority", "infrastructure"),
    ]
    got = pick_mod.pick_todo(
        issues, open_prs=[], lane="infrastructure", extra_exclude=[300]
    )
    assert got is not None
    assert got["number"] == 301


def test_pick_todo_skips_assigned_issues():
    issues = [
        _issue(400, "high-priority", "infrastructure", assignees=[{"login": "alice"}]),
        _issue(401, "high-priority", "infrastructure"),
    ]
    got = pick_mod.pick_todo(issues, open_prs=[], lane="infrastructure")
    assert got is not None
    assert got["number"] == 401


def test_pick_todo_lane_miss_returns_none():
    issues = [_issue(500, "high-priority", "scitex-cloud")]
    assert pick_mod.pick_todo(issues, [], lane="infrastructure") is None


def test_pick_todo_empty_input_returns_none():
    assert pick_mod.pick_todo([], [], lane="infrastructure") is None


# -----------------------------------------------------------------------------
# claimed_numbers_from_comments (todo#469 Bug 2)
# -----------------------------------------------------------------------------


def _gh_api_url(cmd):
    """Extract the URL segment from a gh api command list."""
    # cmd = ["gh", "api", "repos/.../comments?...", ...]
    return cmd[2] if len(cmd) > 2 else ""


def test_claimed_numbers_from_comments_matches_claim_marker(monkeypatch):
    """Issues with recent 'claimed by head-' comments are excluded."""
    import json as _json
    import subprocess

    def _fake_run(cmd, **kwargs):
        url = _gh_api_url(cmd)
        # URL pattern: repos/{repo}/issues/{num}/comments?...
        parts = url.split("/")
        num = int(parts[4]) if len(parts) > 4 else 0
        if num == 600:
            body = _json.dumps([{"body": "claimed by head-mba, forking subagent"}])
        else:
            body = _json.dumps([{"body": "just a normal comment"}])

        class _R:
            stdout = body
            returncode = 0

        return _R()

    monkeypatch.setattr(subprocess, "run", _fake_run)
    result = pick_mod.claimed_numbers_from_comments(
        "ywatanabe1989/todo", [600, 601], window_hours=4
    )
    assert 600 in result
    assert 601 not in result


def test_claimed_numbers_from_comments_no_claims(monkeypatch):
    import json as _json
    import subprocess

    def _fake_run(cmd, **kwargs):
        class _R:
            stdout = _json.dumps([{"body": "just a normal comment"}])
            returncode = 0

        return _R()

    monkeypatch.setattr(subprocess, "run", _fake_run)
    result = pick_mod.claimed_numbers_from_comments(
        "ywatanabe1989/todo", [700], window_hours=4
    )
    assert 700 not in result


def test_claimed_numbers_from_comments_handles_api_error(monkeypatch):
    import subprocess

    def _fail(*_a, **_kw):
        raise subprocess.TimeoutExpired(cmd="gh", timeout=10)

    monkeypatch.setattr(subprocess, "run", _fail)
    result = pick_mod.claimed_numbers_from_comments(
        "ywatanabe1989/todo", [800], window_hours=4
    )
    assert result == set()
