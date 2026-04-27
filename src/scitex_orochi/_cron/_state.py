"""Shared state file for the cron daemon.

The daemon writes one JSON document capturing the last run result for
each job, the next due time, and whether a run is currently in flight.

Everyone else (``scitex-orochi cron list``, ``cron status``, the
heartbeat pusher) reads this file rather than querying the daemon
directly. A file-based contract keeps the design stdlib-only (no
control socket, no IPC) and also means ``cron list`` works even if the
daemon crashed — the last known state is still on disk.

Concurrency: writes go through a best-effort POSIX lock on the file
itself (``fcntl.flock`` on POSIX; no-op fallback on Windows since
Orochi heads are all POSIX anyway). Readers tolerate a partially-written
file by retrying once.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl  # POSIX only

    _HAS_FCNTL = True
except ImportError:  # pragma: no cover — Windows fallback
    _HAS_FCNTL = False


@dataclass
class JobRun:
    """Outcome of one subprocess run for a given job.

    ``stdout_tail`` / ``stderr_tail`` cap at 2048 bytes each so a noisy
    job can't blow up the shared state file. Full output lives in the
    per-job NDJSON log.
    """

    started_at: float = 0.0
    ended_at: float = 0.0
    duration_seconds: float = 0.0
    exit_code: int | None = None
    skipped: str = ""  # e.g. "prev_still_running" | "disabled" | ""
    stdout_tail: str = ""
    stderr_tail: str = ""


@dataclass
class JobState:
    """Per-job runtime state surfaced by ``cron list``."""

    name: str
    interval_seconds: int
    command: str
    timeout_seconds: int
    disabled: bool
    next_run_at: float = 0.0
    running: bool = False
    last_run: JobRun = field(default_factory=JobRun)


@dataclass
class CronState:
    """Snapshot of the whole daemon.

    ``daemon_pid`` is informational — if the daemon crashed, the PID
    may be stale. ``cron status`` pairs it with ``os.kill(pid, 0)`` to
    distinguish "running" from "leftover PID file".
    """

    daemon_pid: int = 0
    daemon_started_at: float = 0.0
    updated_at: float = 0.0
    jobs: list[JobState] = field(default_factory=list)


# ----------------------------------------------------------------------
# File I/O
# ----------------------------------------------------------------------


@contextlib.contextmanager
def _file_lock(path: Path, mode: str) -> Iterator[Any]:
    """Open + lock a file for read or write. No-op on non-POSIX."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, mode) as fh:
        if _HAS_FCNTL:
            lock_op = fcntl.LOCK_EX if "w" in mode or "a" in mode else fcntl.LOCK_SH
            try:
                fcntl.flock(fh.fileno(), lock_op)
            except OSError:
                # Lock contention on read is fine — we'll retry at the
                # caller layer if JSON parse fails.
                pass
        try:
            yield fh
        finally:
            if _HAS_FCNTL:
                with contextlib.suppress(OSError):
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def state_write(state: CronState, path: Path) -> None:
    """Atomically persist a ``CronState`` to disk.

    Write-temp-then-rename so a ``cron list`` that happens mid-write
    never sees a truncated file.
    """
    state.updated_at = time.time()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(state), indent=2, sort_keys=False)
    # Temp file in the same directory so os.replace() is atomic.
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=".state-", suffix=".json", dir=str(path.parent)
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            with contextlib.suppress(OSError):
                os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise


def state_read(path: Path) -> CronState | None:
    """Read and parse the state file. Returns ``None`` if absent.

    Tolerates one partial-write glitch by retrying once after a 50ms
    pause — tight-loop readers (e.g. ``cron list --watch``) don't need
    a more elaborate backoff.
    """
    if not path.is_file():
        return None
    for attempt in range(2):
        try:
            with _file_lock(path, "r") as fh:
                raw = fh.read()
            data = json.loads(raw)
            return _state_from_dict(data)
        except (json.JSONDecodeError, ValueError):
            if attempt == 0:
                time.sleep(0.05)
                continue
            return None
    return None


def _state_from_dict(data: dict[str, Any]) -> CronState:
    jobs = []
    for j in data.get("jobs", []) or []:
        last_run_raw = j.get("last_run", {}) or {}
        jobs.append(
            JobState(
                name=j.get("name", ""),
                interval_seconds=int(j.get("interval_seconds", 0) or 0),
                command=j.get("command", ""),
                timeout_seconds=int(j.get("timeout_seconds", 0) or 0),
                disabled=bool(j.get("disabled", False)),
                next_run_at=float(j.get("next_run_at", 0) or 0),
                running=bool(j.get("running", False)),
                last_run=JobRun(
                    started_at=float(last_run_raw.get("started_at", 0) or 0),
                    ended_at=float(last_run_raw.get("ended_at", 0) or 0),
                    duration_seconds=float(
                        last_run_raw.get("duration_seconds", 0) or 0
                    ),
                    exit_code=last_run_raw.get("exit_code"),
                    skipped=last_run_raw.get("skipped", "") or "",
                    stdout_tail=last_run_raw.get("stdout_tail", "") or "",
                    stderr_tail=last_run_raw.get("stderr_tail", "") or "",
                ),
            )
        )
    return CronState(
        daemon_pid=int(data.get("daemon_pid", 0) or 0),
        daemon_started_at=float(data.get("daemon_started_at", 0) or 0),
        updated_at=float(data.get("updated_at", 0) or 0),
        jobs=jobs,
    )


def render_cron_jobs(state: CronState | None) -> list[dict[str, Any]]:
    """Normalise state → the array shape surfaced by ``cron list`` and
    the heartbeat payload. Both callers want the same keys so the UI
    (Phase 2) has one contract to render.

    Returns ``[]`` if state is unavailable (daemon never started, state
    file missing/corrupt). Empty list is distinguishable from "daemon
    running but 0 jobs" because the latter returns an empty jobs array
    too — by design the UI just says "no jobs".
    """
    if state is None:
        return []
    out: list[dict[str, Any]] = []
    for j in state.jobs:
        out.append(
            {
                "name": j.name,
                "interval": j.interval_seconds,
                "last_run": j.last_run.ended_at or j.last_run.started_at or None,
                "last_exit": j.last_run.exit_code,
                "last_skipped": j.last_run.skipped or None,
                "last_duration_seconds": j.last_run.duration_seconds or None,
                "next_run": j.next_run_at or None,
                "running": j.running,
                "disabled": j.disabled,
                "command": j.command,
                "timeout": j.timeout_seconds,
            }
        )
    return out
