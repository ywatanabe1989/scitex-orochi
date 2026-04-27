"""End-to-end tests for the Orochi cron daemon.

Runs the real ``CronDaemon`` against a tiny YAML that uses fast (1s)
intervals + trivial shell commands so the test stays under a second.
Covers:

* ``run_once`` fires a job synchronously and returns exit + output.
* ``load`` populates state; failed command records non-zero exit.
* Concurrent-run-guard: a slow job firing twice within its interval
  records ``skipped="prev_still_running"``.
* Timeout: a command that overruns is killed with ``skipped="timeout_after_*"``.
* State file is readable mid-run.
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

import pytest

from scitex_orochi._cron import CronDaemon, state_read
from scitex_orochi._cron._daemon import (
    CronDaemon as _CD,  # noqa: F401 — explicit import
)
from scitex_orochi._cron._state import render_cron_jobs


def _mk_config(tmp_path: Path, yaml_body: str) -> Path:
    cfg = tmp_path / "cron.yaml"
    cfg.write_text(textwrap.dedent(yaml_body))
    return cfg


def _mk_daemon(tmp_path: Path, cfg: Path) -> CronDaemon:
    return CronDaemon(
        config_path=cfg,
        state_path=tmp_path / "state.json",
        pid_path=tmp_path / "daemon.orochi_pid",
        log_dir=tmp_path / "logs",
    )


def test_run_once_echo(tmp_path):
    cfg = _mk_config(
        tmp_path,
        """
        jobs:
          - name: ping
            interval: 5m
            command: "/bin/echo hello"
        """,
    )
    d = _mk_daemon(tmp_path, cfg)
    run = d.run_once("ping")
    assert run.exit_code == 0
    assert "hello" in run.stdout_tail


def test_run_once_unknown_job(tmp_path):
    cfg = _mk_config(
        tmp_path,
        """
        jobs:
          - name: ping
            interval: 5m
            command: "/bin/true"
        """,
    )
    d = _mk_daemon(tmp_path, cfg)
    with pytest.raises(KeyError):
        d.run_once("nope")


def test_run_once_dry_run_doesnt_execute(tmp_path):
    cfg = _mk_config(
        tmp_path,
        """
        jobs:
          - name: destructive
            interval: 5m
            command: "/bin/false"
        """,
    )
    d = CronDaemon(config_path=cfg, dry_run=True)
    run = d.run_once("destructive")
    assert run.exit_code == 0
    assert "dry-run" in run.stdout_tail


def test_run_once_captures_nonzero_exit(tmp_path):
    cfg = _mk_config(
        tmp_path,
        """
        jobs:
          - name: fail
            interval: 5m
            command: "/bin/sh -c 'echo err >&2; exit 3'"
        """,
    )
    d = _mk_daemon(tmp_path, cfg)
    run = d.run_once("fail")
    assert run.exit_code == 3
    assert "err" in run.stderr_tail


def test_run_once_timeout(tmp_path):
    cfg = _mk_config(
        tmp_path,
        """
        jobs:
          - name: slow
            interval: 5m
            timeout: 1s
            command: "/bin/sh -c 'sleep 5'"
        """,
    )
    d = _mk_daemon(tmp_path, cfg)
    run = d.run_once("slow")
    assert run.skipped.startswith("timeout_after_")


def test_load_populates_state_file(tmp_path):
    cfg = _mk_config(
        tmp_path,
        """
        jobs:
          - name: a
            interval: 1m
            command: "/bin/true"
          - name: b
            interval: 2m
            command: "/bin/true"
            disabled: true
        """,
    )
    d = _mk_daemon(tmp_path, cfg)
    d.load()
    state = state_read(tmp_path / "state.json")
    assert state is not None
    assert len(state.jobs) == 2
    rendered = render_cron_jobs(state)
    names = {j["name"] for j in rendered}
    assert names == {"a", "b"}
    disabled_flags = {j["name"]: j["disabled"] for j in rendered}
    assert disabled_flags == {"a": False, "b": True}


def test_concurrent_run_guard_skips_overlap(tmp_path):
    """A second dispatch while the first is still running must be
    recorded as skipped, not queued.

    We trigger this by calling ``_dispatch`` twice back-to-back on a
    slow job; the worker-thread slot for the second call should detect
    the first is still orochi_alive and return without spawning.
    """
    cfg = _mk_config(
        tmp_path,
        """
        jobs:
          - name: slow
            interval: 1m
            command: "/bin/sh -c 'sleep 1'"
        """,
    )
    d = _mk_daemon(tmp_path, cfg)
    d.load()
    js = d._state.jobs[0]  # type: ignore[attr-defined]
    now = time.time()
    d._dispatch(js, now)  # type: ignore[attr-defined]
    # Second dispatch must hit the run-guard. Small sleep to ensure the
    # worker thread has actually started.
    time.sleep(0.05)
    d._dispatch(js, now)  # type: ignore[attr-defined]
    # Inspect state (reload snapshot).
    state = state_read(tmp_path / "state.json")
    assert state is not None
    row = next(j for j in state.jobs if j.name == "slow")
    assert row.last_run.skipped == "prev_still_running"
    # Drain the still-running first worker so pytest teardown doesn't
    # hang on a lingering thread (CronDaemon workers are daemon=True,
    # but explicit join keeps logs clean).
    d._drain_workers(grace_seconds=3.0)  # type: ignore[attr-defined]
