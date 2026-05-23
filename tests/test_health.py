"""Unit tests for :mod:`scitex_orochi._health` — fleet-wide health classification."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scitex_orochi._health import (
    DEAD_THRESHOLD,
    ESCALATE_THRESHOLD,
    NUDGE_THRESHOLD,
    AgentSnapshot,
    HealthState,
    classify,
)


def _iso_now_minus(seconds: int) -> str:
    """ISO-8601 UTC timestamp ``seconds`` ago. Wire-format match."""
    ts = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def _snapshot(**overrides: object) -> AgentSnapshot:
    """Build an AgentSnapshot with sensible defaults, overridable per-test."""
    defaults: dict[str, object] = {
        "name": "head@mba",
        "machine": "mba",
        "status": "online",
        "liveness": "online",
        "idle_seconds": 0,
        "orochi_current_task": "",
        "last_heartbeat": _iso_now_minus(5),
        "sac_health": None,
    }
    defaults.update(overrides)
    return AgentSnapshot(**defaults)  # type: ignore[arg-type]


def test_thresholds_are_positive_seconds():
    """Sanity: thresholds are non-zero positive seconds in expected order."""
    assert 0 < NUDGE_THRESHOLD < ESCALATE_THRESHOLD
    assert DEAD_THRESHOLD > 0


def test_classify_returns_ok_for_healthy_recent_heartbeat():
    """Online, recent heartbeat, no idleness → OK."""
    assert classify(_snapshot()) is HealthState.OK


def test_classify_returns_dead_when_status_offline():
    """status='offline' is a hard-DEAD signal regardless of other fields."""
    snap = _snapshot(status="offline")
    assert classify(snap) is HealthState.DEAD


def test_classify_returns_dead_when_heartbeat_older_than_dead_threshold():
    """An agent silent for > DEAD_THRESHOLD seconds is presumed DEAD."""
    snap = _snapshot(last_heartbeat=_iso_now_minus(DEAD_THRESHOLD + 30))
    assert classify(snap) is HealthState.DEAD


def test_classify_returns_dead_when_sac_health_false_overrides_freshness():
    """SAC's binary verdict beats heartbeat freshness."""
    snap = _snapshot(
        last_heartbeat=_iso_now_minus(1),  # fresh
        sac_health=False,
    )
    assert classify(snap) is HealthState.DEAD


def test_classify_returns_stale_when_liveness_stale():
    """liveness='stale' surfaces as STALE state."""
    snap = _snapshot(liveness="stale", orochi_current_task="do thing")
    assert classify(snap) is HealthState.STALE


def test_classify_returns_idle_when_idle_and_has_task():
    """Idle + assigned task → IDLE (silent-with-task is the actionable case)."""
    snap = _snapshot(
        liveness="idle",
        idle_seconds=NUDGE_THRESHOLD + 1,
        orochi_current_task="finalize migration",
    )
    assert classify(snap) is HealthState.IDLE


def test_classify_returns_ok_when_idle_but_no_task():
    """Idle with no assigned task is not actionable → OK."""
    snap = _snapshot(liveness="idle", idle_seconds=300, orochi_current_task="")
    assert classify(snap) is HealthState.OK


def test_health_state_members_are_string_comparable():
    """HealthState.OK == 'ok' so legacy string-literal callers still work."""
    assert HealthState.OK == "ok"
    assert HealthState.IDLE == "idle"
    assert HealthState.STALE == "stale"
    assert HealthState.DEAD == "dead"


def test_agent_snapshot_heartbeat_age_seconds_handles_missing_timestamp():
    """Missing or unparseable last_heartbeat → None (don't crash)."""
    assert _snapshot(last_heartbeat=None).heartbeat_age_seconds is None
    assert _snapshot(last_heartbeat="not-an-iso").heartbeat_age_seconds is None


def test_agent_snapshot_heartbeat_age_seconds_reflects_recency():
    """heartbeat_age_seconds reflects roughly how long ago last_heartbeat was."""
    snap = _snapshot(last_heartbeat=_iso_now_minus(42))
    assert snap.heartbeat_age_seconds is not None
    # Within a generous window — clock skew + test-runner pauses.
    assert 40 <= snap.heartbeat_age_seconds <= 50


@pytest.mark.parametrize(
    "status,liveness,task,sac,expected",
    [
        ("offline", "online", "", None, HealthState.DEAD),
        ("online", "stale", "", None, HealthState.STALE),
        ("online", "idle", "x", None, HealthState.IDLE),
        ("online", "online", "x", None, HealthState.OK),
        ("online", "online", "x", False, HealthState.DEAD),  # SAC overrides
        ("online", "online", "x", True, HealthState.OK),  # SAC affirmative
    ],
)
def test_classify_state_table(status, liveness, task, sac, expected):
    """Tabular sweep of the (status, liveness, task, sac_health) state space."""
    snap = _snapshot(
        status=status,
        liveness=liveness,
        orochi_current_task=task,
        sac_health=sac,
    )
    assert classify(snap) is expected
