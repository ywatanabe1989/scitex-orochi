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
