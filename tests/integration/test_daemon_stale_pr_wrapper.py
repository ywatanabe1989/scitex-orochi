"""Wrapper-level tests for ``daemon-stale-pr`` (FR-N).

Covers lead msg#23297 acceptance:
  1. Synthetic gitea mock with 1 stale PR → 1 DM emitted to merger.
  2. Same PR on second run within 1h → no duplicate DM.

We patch out the gitea HTTP client and the hub-message poster so the
test stays sealed (no network, no side files outside ``tmp_path``).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from scitex_orochi._daemons._stale_pr import _wrapper as wrapper_mod
from scitex_orochi._daemons._stale_pr._state import StalePrState
from scitex_orochi._daemons._stale_pr._wrapper import (
    StalePrConfig,
    run_tick_async,
)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def now_ts() -> float:
    return datetime(2026, 4, 29, 19, 0, 0, tzinfo=timezone.utc).timestamp()


@pytest.fixture
def stale_pr_payload(now_ts: float) -> dict:
    created = datetime.fromtimestamp(now_ts, tz=timezone.utc) - timedelta(hours=2)
    return {
        "number": 388,
        "mergeable": True,
        "created_at": _iso(created),
        "title": "fix: example",
        "user": {"login": "ywatanabe"},
        "head": {"sha": "abc123def456"},
    }


@pytest.fixture
def cfg(tmp_path: Path) -> StalePrConfig:
    return StalePrConfig(
        gitea_base_url="https://gitea.example.com",
        gitea_token="GTOKEN",
        gitea_owner="scitex",
        repos=["scitex-orochi"],
        repo_to_merger={"scitex-orochi": "head-mba"},
        sender="daemon-stale-pr",
        hub_url="https://hub.example.com",
        hub_token="HTOKEN",
        publish_channel="#general",
        threshold_s=3600,
        redm_after_s=3600,
        tick_interval_s=600,
        log_path=tmp_path / "stale-pr-daemon.log",
    )


def _async_return(value: Any):
    async def _coro(*_a, **_kw):
        return value

    return _coro


def test_acceptance_1_one_stale_pr_emits_one_dm(
    cfg: StalePrConfig,
    stale_pr_payload: dict,
    now_ts: float,
    tmp_path: Path,
) -> None:
    state = StalePrState(tmp_path / "state.json")

    fetch_payload = (
        [stale_pr_payload],
        {stale_pr_payload["head"]["sha"]: {"state": "success"}},
    )
    posts: list[dict] = []

    def fake_post_message(**kwargs):
        posts.append(kwargs)
        return True

    with patch.object(
        wrapper_mod, "_fetch_repo_state", _async_return(fetch_payload)
    ), patch.object(wrapper_mod, "_post_message", side_effect=fake_post_message):
        result = asyncio.run(run_tick_async(cfg, state, now_ts=now_ts))

    assert result.found == 1
    assert result.dispatched == 1
    assert result.suppressed == 0
    # Two POSTs: the merger DM + the publish-channel summary.
    assert len(posts) == 2
    dm_post = next(p for p in posts if p["channel"].startswith("dm:"))
    assert dm_post["channel"] == "dm:agent:daemon-stale-pr|agent:head-mba"
    assert "scitex-orochi#388" in dm_post["text"]
    summary_post = next(p for p in posts if p["channel"] == "#general")
    assert "tick=stale-pr" in summary_post["text"]
    assert "found=1" in summary_post["text"]
    assert "dispatched=1" in summary_post["text"]
    # State file must persist the dispatch — otherwise acceptance #2
    # below would fail because the daemon would re-DM on the next tick.
    reread = StalePrState(state.path)
    reread.load()
    assert "scitex-orochi#388" in reread.last_notified_ts


def test_acceptance_2_repeat_within_window_does_not_redm(
    cfg: StalePrConfig,
    stale_pr_payload: dict,
    now_ts: float,
    tmp_path: Path,
) -> None:
    state = StalePrState(tmp_path / "state.json")
    state.load()
    state.record_notified("scitex-orochi#388", when=now_ts - 600)  # 10min ago

    fetch_payload = (
        [stale_pr_payload],
        {stale_pr_payload["head"]["sha"]: {"state": "success"}},
    )
    posts: list[dict] = []

    def fake_post_message(**kwargs):
        posts.append(kwargs)
        return True

    with patch.object(
        wrapper_mod, "_fetch_repo_state", _async_return(fetch_payload)
    ), patch.object(wrapper_mod, "_post_message", side_effect=fake_post_message):
        result = asyncio.run(run_tick_async(cfg, state, now_ts=now_ts))

    assert result.found == 1
    assert result.dispatched == 0
    assert result.suppressed == 1
    # Only the publish-channel summary should be posted; no DM.
    assert all(not p["channel"].startswith("dm:") for p in posts)


def test_no_merger_configured_records_error_but_does_not_crash(
    cfg: StalePrConfig,
    stale_pr_payload: dict,
    now_ts: float,
    tmp_path: Path,
) -> None:
    cfg.repo_to_merger = {}  # forget all routes
    state = StalePrState(tmp_path / "state.json")

    fetch_payload = (
        [stale_pr_payload],
        {stale_pr_payload["head"]["sha"]: {"state": "success"}},
    )

    with patch.object(
        wrapper_mod, "_fetch_repo_state", _async_return(fetch_payload)
    ), patch.object(wrapper_mod, "_post_message", return_value=True):
        result = asyncio.run(run_tick_async(cfg, state, now_ts=now_ts))

    assert result.found == 1
    assert result.dispatched == 0
    assert any("no merger configured" in e for e in result.errors)
