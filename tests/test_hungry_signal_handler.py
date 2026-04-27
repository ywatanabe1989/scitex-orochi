"""Unit tests for scripts/server/hungry-signal-handler.py (Layer 2 — lead-side).

Exercise the pure-function core of the lead-side responder:

* ``parse_hungry_signal`` — DM format round-trips
* ``pick_for_lane``       — skips claimed + audit-flagged + assigned issues;
                             prefers lane match; falls back to unlabelled
* ``format_dispatch_reply`` + ``handle_hungry_message`` — end-to-end shape

No network — ``gh`` is never shelled out in these tests.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HANDLER = REPO_ROOT / "scripts" / "server" / "hungry-signal-handler.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("hungry_signal_handler", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


handler = _load_module()


# -----------------------------------------------------------------------------
# parse_hungry_signal
# -----------------------------------------------------------------------------


def test_parse_hungry_signal_canonical_shape():
    text = (
        "head-mba: hungry — 0 orochi_subagents × 2 cycles, ready for dispatch. "
        "lane: infrastructure, alive: head-mba,healer-mba"
    )
    got = handler.parse_hungry_signal(text)
    assert got == {"sender": "head-mba", "lane": "infrastructure"}


def test_parse_hungry_signal_handles_multi_word_lane():
    text = (
        "head-ywata-note-win: hungry — 0 orochi_subagents × 2 cycles, ready for "
        "dispatch. lane: specialized-wsl-access, alive: head-ywata-note-win"
    )
    got = handler.parse_hungry_signal(text)
    assert got is not None
    assert got["sender"] == "head-ywata-note-win"
    assert got["lane"] == "specialized-wsl-access"


def test_parse_hungry_signal_rejects_unrelated_dm():
    assert handler.parse_hungry_signal("hey lead, ping") is None
    assert handler.parse_hungry_signal("") is None
    assert handler.parse_hungry_signal(None) is None  # type: ignore[arg-type]


def test_parse_hungry_signal_rejects_malformed_no_lane():
    # Missing "lane: ..." segment — refuse rather than guess.
    text = "head-mba: hungry — 0 orochi_subagents × 2 cycles, ready for dispatch."
    assert handler.parse_hungry_signal(text) is None


# -----------------------------------------------------------------------------
# claimed_numbers_from_prs
# -----------------------------------------------------------------------------


def test_claimed_numbers_from_prs_collects_title_and_body():
    prs = [
        {"title": "fix(scope): thing (#123)", "body": "also closes #124"},
        {"title": "no refs here", "body": ""},
        {"title": "chore: drop stale flag", "body": "refs todo#300"},
    ]
    assert handler.claimed_numbers_from_prs(prs) == {123, 124, 300}


# -----------------------------------------------------------------------------
# pick_for_lane
# -----------------------------------------------------------------------------


def _issue(num, *labels, assignees=(), title=None):
    return {
        "number": num,
        "title": title or f"feat: thing {num}",
        "labels": [{"name": lab} for lab in labels],
        "assignees": list(assignees),
    }


def test_pick_for_lane_returns_first_lane_match():
    issues = [
        _issue(100, "high-priority", "infrastructure"),
        _issue(101, "high-priority", "scitex-cloud"),
        _issue(102, "high-priority", "infrastructure"),
    ]
    got = handler.pick_for_lane(issues, open_prs=[], lane="infrastructure")
    assert got is not None
    assert got["number"] == 100
    assert "direct-match" in got["reason"]


def test_pick_for_lane_skips_issues_claimed_by_open_pr():
    issues = [
        _issue(200, "high-priority", "infrastructure"),
        _issue(201, "high-priority", "infrastructure"),
    ]
    open_prs = [{"title": "wip: #200", "body": ""}]
    got = handler.pick_for_lane(issues, open_prs, lane="infrastructure")
    assert got is not None
    assert got["number"] == 201


def test_pick_for_lane_skips_audit_review_label():
    issues = [
        _issue(300, "high-priority", "infrastructure", handler.AUDIT_REVIEW_LABEL),
        _issue(301, "high-priority", "infrastructure"),
    ]
    got = handler.pick_for_lane(issues, open_prs=[], lane="infrastructure")
    assert got is not None
    assert got["number"] == 301


def test_pick_for_lane_custom_audit_label_argument_overrides_default():
    issues = [
        _issue(310, "high-priority", "infrastructure", "custom-audit-flag"),
        _issue(311, "high-priority", "infrastructure"),
    ]
    got = handler.pick_for_lane(
        issues, open_prs=[], lane="infrastructure", audit_label="custom-audit-flag"
    )
    assert got is not None
    assert got["number"] == 311


def test_pick_for_lane_skips_issues_already_assigned():
    issues = [
        _issue(400, "high-priority", "infrastructure", assignees=[{"login": "alice"}]),
        _issue(401, "high-priority", "infrastructure"),
    ]
    got = handler.pick_for_lane(issues, open_prs=[], lane="infrastructure")
    assert got is not None
    assert got["number"] == 401


def test_pick_for_lane_falls_back_to_unlabelled_when_no_lane_match():
    issues = [
        _issue(500, "high-priority", "scitex-cloud"),   # wrong lane
        _issue(501, "high-priority"),                    # unlabelled: eligible fallback
        _issue(502, "high-priority", "hub-admin"),       # wrong lane
    ]
    got = handler.pick_for_lane(issues, open_prs=[], lane="infrastructure")
    assert got is not None
    assert got["number"] == 501
    assert "fallback" in got["reason"]


def test_pick_for_lane_prefers_direct_match_over_fallback():
    # Unlabelled issue first in list, direct lane match later: direct
    # match must still win over the fallback to preserve routing quality.
    issues = [
        _issue(600, "high-priority"),                       # unlabelled fallback
        _issue(601, "high-priority", "infrastructure"),      # direct match
    ]
    got = handler.pick_for_lane(issues, open_prs=[], lane="infrastructure")
    assert got is not None
    assert got["number"] == 601


def test_pick_for_lane_extra_exclude_skips_recently_dispatched():
    issues = [
        _issue(700, "high-priority", "infrastructure"),
        _issue(701, "high-priority", "infrastructure"),
    ]
    got = handler.pick_for_lane(
        issues, open_prs=[], lane="infrastructure", extra_exclude=[700]
    )
    assert got is not None
    assert got["number"] == 701


def test_pick_for_lane_returns_none_when_nothing_eligible():
    # Everything is either claimed, assigned, or audit-flagged → None.
    issues = [
        _issue(800, "high-priority", "infrastructure", assignees=[{"login": "a"}]),
        _issue(801, "high-priority", "infrastructure", handler.AUDIT_REVIEW_LABEL),
    ]
    open_prs = [{"title": "#801", "body": ""}]
    got = handler.pick_for_lane(issues, open_prs, lane="infrastructure")
    assert got is None


# -----------------------------------------------------------------------------
# format_dispatch_reply / handle_hungry_message
# -----------------------------------------------------------------------------


def test_format_dispatch_reply_shape_with_brief():
    pick = {"number": 42, "title": "feat: do thing", "reason": ""}
    reply = handler.format_dispatch_reply(
        pick, sender="head-mba", lane="infrastructure", brief="land PR first"
    )
    assert reply.startswith("dispatch: todo#42 — feat: do thing")
    assert "land PR first" in reply


def test_format_dispatch_reply_none_match_explicit():
    reply = handler.format_dispatch_reply(
        None, sender="head-mba", lane="infrastructure"
    )
    assert "dispatch: none" in reply
    assert "head-mba" in reply
    assert "infrastructure" in reply


def test_handle_hungry_message_end_to_end():
    dm_text = (
        "head-mba: hungry — 0 orochi_subagents × 2 cycles, ready for dispatch. "
        "lane: infrastructure, alive: head-mba"
    )
    issues = [
        _issue(900, "high-priority", "infrastructure", title="feat: ship layer-2"),
    ]
    result = handler.handle_hungry_message(dm_text, issues, [])
    assert result is not None
    assert result["sender"] == "head-mba"
    assert result["lane"] == "infrastructure"
    assert result["pick"]["number"] == 900
    assert "todo#900" in result["reply"]


def test_handle_hungry_message_returns_none_on_unrelated_dm():
    assert handler.handle_hungry_message("hi lead", [], []) is None
