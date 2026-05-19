"""Unit tests for ``daemon-stale-pr`` pure predicates (FR-N).

Lead msg#23297 acceptance:
  * Synthetic gitea mock with 1 stale PR → 1 DM emitted to merger.
  * Same PR on second run within 1h → no duplicate DM.

The first half is covered by :mod:`test_daemon_stale_pr_wrapper`
(wrapper integration). These tests pin the rule logic and debounce
in isolation so a future refactor doesn't drift the meaning of
"stale".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scitex_orochi._daemons._stale_pr._check import (
    StalePrFinding,
    _DebounceView,
    findings_from_payload,
    is_stale,
    select_stale_for_dm,
)


def _iso(dt: datetime) -> str:
    """Render a UTC datetime in the ``Z``-suffixed shape gitea returns."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def now_dt() -> datetime:
    return datetime(2026, 4, 29, 19, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def now_ts(now_dt: datetime) -> float:
    return now_dt.timestamp()


def _pr(*, age_minutes: int, mergeable: bool, sha: str = "abc1234") -> dict:
    created = datetime(2026, 4, 29, 19, 0, 0, tzinfo=timezone.utc) - timedelta(
        minutes=age_minutes
    )
    return {
        "number": 388,
        "mergeable": mergeable,
        "created_at": _iso(created),
        "title": "fix: example",
        "user": {"login": "ywatanabe"},
        "head": {"sha": sha},
    }


class TestIsStale:
    def test_old_mergeable_green_is_stale(self, now_ts: float) -> None:
        assert is_stale(
            _pr(age_minutes=120, mergeable=True),
            {"state": "success"},
            threshold_s=3600,
            now_ts=now_ts,
        )

    def test_below_threshold_is_not_stale(self, now_ts: float) -> None:
        assert not is_stale(
            _pr(age_minutes=30, mergeable=True),
            {"state": "success"},
            threshold_s=3600,
            now_ts=now_ts,
        )

    def test_unmergeable_is_not_stale(self, now_ts: float) -> None:
        assert not is_stale(
            _pr(age_minutes=120, mergeable=False),
            {"state": "success"},
            threshold_s=3600,
            now_ts=now_ts,
        )

    def test_pending_ci_is_not_stale(self, now_ts: float) -> None:
        assert not is_stale(
            _pr(age_minutes=120, mergeable=True),
            {"state": "pending"},
            threshold_s=3600,
            now_ts=now_ts,
        )

    def test_failure_ci_is_not_stale(self, now_ts: float) -> None:
        assert not is_stale(
            _pr(age_minutes=120, mergeable=True),
            {"state": "failure"},
            threshold_s=3600,
            now_ts=now_ts,
        )

    def test_no_ci_state_is_not_stale(self, now_ts: float) -> None:
        # Empty state is gitea's "no checks reported" — we conservatively
        # refuse to call this success (see _check.is_stale docstring).
        assert not is_stale(
            _pr(age_minutes=120, mergeable=True),
            {"state": ""},
            threshold_s=3600,
            now_ts=now_ts,
        )

    def test_missing_created_at_is_not_stale(self, now_ts: float) -> None:
        bad = _pr(age_minutes=120, mergeable=True)
        bad.pop("created_at")
        assert not is_stale(bad, {"state": "success"}, threshold_s=3600, now_ts=now_ts)


class TestSelectStaleForDm:
    def test_first_time_finding_is_dispatched(self, now_ts: float) -> None:
        f = StalePrFinding(
            repo="scitex-orochi",
            number=388,
            sha="abc",
            age_seconds=7200,
            title="x",
            author="y",
        )
        state = _DebounceView()
        out = select_stale_for_dm([f], state, redm_after_s=3600, now_ts=now_ts)
        assert out == [f]

    def test_recent_notification_suppresses_redm(self, now_ts: float) -> None:
        # Acceptance test #2 from FR-N: same PR on second run within 1h
        # → no duplicate DM.
        f = StalePrFinding(
            repo="scitex-orochi",
            number=388,
            sha="abc",
            age_seconds=7200,
            title="x",
            author="y",
        )
        state = _DebounceView(last_notified_ts={f.key: now_ts - 600})  # 10min ago
        out = select_stale_for_dm([f], state, redm_after_s=3600, now_ts=now_ts)
        assert out == []

    def test_old_notification_allows_redm(self, now_ts: float) -> None:
        f = StalePrFinding(
            repo="scitex-orochi",
            number=388,
            sha="abc",
            age_seconds=7200,
            title="x",
            author="y",
        )
        # 2h ago — past the 1h debounce window, so re-DM allowed.
        state = _DebounceView(last_notified_ts={f.key: now_ts - 7200})
        out = select_stale_for_dm([f], state, redm_after_s=3600, now_ts=now_ts)
        assert out == [f]

    def test_does_not_mutate_state(self, now_ts: float) -> None:
        f = StalePrFinding(
            repo="x", number=1, sha="a", age_seconds=7200, title="", author=""
        )
        state = _DebounceView()
        select_stale_for_dm([f], state, redm_after_s=3600, now_ts=now_ts)
        # Wrapper records the dispatch only after the DM POST succeeds —
        # selection itself must not write to the state, otherwise a
        # transient hub outage would silently swallow alerts.
        assert state.last_notified_ts == {}


class TestFindingsFromPayload:
    def test_walks_pulls_and_attaches_status(self, now_ts: float) -> None:
        pulls = [
            _pr(age_minutes=120, mergeable=True, sha="aaa1"),
            _pr(age_minutes=10, mergeable=True, sha="bbb2"),  # too young
            _pr(age_minutes=120, mergeable=False, sha="ccc3"),  # not mergeable
        ]
        # Vary a couple of titles/numbers so duplicates don't shadow.
        pulls[1]["number"] = 389
        pulls[2]["number"] = 390
        status_lookup = {
            "aaa1": {"state": "success"},
            "bbb2": {"state": "success"},
            "ccc3": {"state": "success"},
        }
        out = findings_from_payload(
            pulls,
            status_lookup,
            "scitex-orochi",
            threshold_s=3600,
            now_ts=now_ts,
        )
        assert [(f.repo, f.number, f.sha) for f in out] == [
            ("scitex-orochi", 388, "aaa1"),
        ]

    def test_missing_status_treated_as_no_check(self, now_ts: float) -> None:
        pulls = [_pr(age_minutes=120, mergeable=True, sha="aaa1")]
        out = findings_from_payload(
            pulls, {}, "scitex-orochi", threshold_s=3600, now_ts=now_ts
        )
        assert out == []
