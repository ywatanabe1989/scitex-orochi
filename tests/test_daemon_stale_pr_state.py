"""Unit tests for the ``daemon-stale-pr`` JSON state store."""

from __future__ import annotations

import json
from pathlib import Path

from scitex_orochi._daemons._stale_pr._state import StalePrState


def test_load_missing_file_is_empty(tmp_path: Path) -> None:
    state = StalePrState(tmp_path / "missing.json")
    state.load()
    assert state.last_notified_ts == {}


def test_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    a = StalePrState(p)
    a.load()
    a.record_notified("scitex-orochi#388", when=1700000000.0)
    a.record_notified("scitex/orochi-tools#1", when=1700001000.0)
    b = StalePrState(p)
    b.load()
    assert b.last_notified_ts == {
        "scitex-orochi#388": 1700000000.0,
        "scitex/orochi-tools#1": 1700001000.0,
    }


def test_corrupt_json_is_quarantined_to_bak(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    p.write_text("{not json")
    state = StalePrState(p)
    state.load()
    assert state.last_notified_ts == {}
    # Operator should be able to inspect what was clobbered, so we
    # rename rather than overwrite. The .bak suffix is for forensic
    # use, not auto-recovery.
    assert (tmp_path / "state.json.bak").exists()


def test_non_numeric_value_dropped(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"good#1": 1700000000, "bad#1": "wat"}))
    state = StalePrState(p)
    state.load()
    assert state.last_notified_ts == {"good#1": 1700000000.0}


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    p = tmp_path / "nested" / "deeper" / "state.json"
    state = StalePrState(p)
    state.load()
    state.record_notified("k", when=1.0)
    assert p.exists()
    assert json.loads(p.read_text()) == {"k": 1.0}
