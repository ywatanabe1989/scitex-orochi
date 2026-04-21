"""Unit tests for ``scitex_orochi._cron._config``.

Covers the YAML loader, interval parsing, and var expansion. These are
the pieces an operator hits first — a broken config should fail at
``load_config`` with a clear error, not at job-run time.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from scitex_orochi._cron._config import (
    expand_vars,
    load_config,
    parse_interval,
)

# ----------------------------------------------------------------------
# parse_interval
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("30s", 30),
        ("5m", 300),
        ("1h", 3600),
        ("1d", 86400),
        ("10", 10),
        (10, 10),
        ("2M", 120),  # case-insensitive
    ],
)
def test_parse_interval_happy(value, expected):
    assert parse_interval(value) == expected


@pytest.mark.parametrize("bad", ["", "abc", "0", 0, -5, "5x", None])
def test_parse_interval_rejects_bad(bad):
    with pytest.raises((ValueError, TypeError)):
        parse_interval(bad)  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# expand_vars
# ----------------------------------------------------------------------


def test_expand_vars_replaces_known():
    out = expand_vars("bash ${ROOT}/a.sh", {"ROOT": "/tmp/x"})
    assert out == "bash /tmp/x/a.sh"


def test_expand_vars_leaves_unknown_visible():
    # Typos shouldn't silently become empty strings — otherwise the
    # wrong command executes quietly.
    out = expand_vars("bash ${TYPO}/a.sh", {"ROOT": "/tmp/x"})
    assert out == "bash ${TYPO}/a.sh"


# ----------------------------------------------------------------------
# load_config
# ----------------------------------------------------------------------


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "cron.yaml"
    p.write_text(textwrap.dedent(text))
    return p


def test_load_config_parses_defaults(tmp_path):
    p = _write(
        tmp_path,
        """
        jobs:
          - name: ping
            interval: 30s
            command: "echo hi"
          - name: slow
            interval: 1h
            command: "sleep 1"
            timeout: 10m
            disabled: true
        """,
    )
    cfg = load_config(p)
    assert cfg.tick_seconds == 10  # default
    assert len(cfg.jobs) == 2
    a, b = cfg.jobs
    assert a.name == "ping"
    assert a.interval_seconds == 30
    assert a.timeout_seconds == 600  # default
    assert not a.disabled
    assert b.interval_seconds == 3600
    assert b.timeout_seconds == 600
    assert b.disabled


def test_load_config_expands_repo_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SCITEX_OROCHI_REPO_ROOT", "/opt/scitex")
    p = _write(
        tmp_path,
        """
        jobs:
          - name: probe
            interval: 5m
            command: "bash ${SCITEX_OROCHI_REPO_ROOT}/a.sh"
        """,
    )
    cfg = load_config(p)
    assert cfg.jobs[0].command == "bash /opt/scitex/a.sh"


def test_load_config_rejects_duplicate_names(tmp_path):
    p = _write(
        tmp_path,
        """
        jobs:
          - name: dup
            interval: 1m
            command: "echo a"
          - name: dup
            interval: 1m
            command: "echo b"
        """,
    )
    with pytest.raises(ValueError, match="duplicate job name"):
        load_config(p)


def test_load_config_missing_file(tmp_path):
    missing = tmp_path / "nope.yaml"
    with pytest.raises(FileNotFoundError):
        load_config(missing)


def test_load_config_rejects_missing_command(tmp_path):
    p = _write(
        tmp_path,
        """
        jobs:
          - name: bad
            interval: 1m
        """,
    )
    with pytest.raises(ValueError, match="missing 'command'"):
        load_config(p)


def test_load_config_rejects_bad_interval(tmp_path):
    p = _write(
        tmp_path,
        """
        jobs:
          - name: bad
            interval: "hello"
            command: "echo"
        """,
    )
    with pytest.raises(ValueError, match="unparseable interval"):
        load_config(p)
