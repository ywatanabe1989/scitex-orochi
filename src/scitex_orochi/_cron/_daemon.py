"""Orochi unified cron daemon — the scheduling core.

Design in one paragraph
-----------------------
Single Python process. One main thread sleeps for ``tick_seconds``,
wakes up, and for every job whose ``next_run_at`` has passed spawns a
subprocess in a worker thread. Each worker captures exit + stdout/stderr
tails, updates the shared ``CronState`` under a lock, and writes the
state file + appends an NDJSON log line. Run-in-progress jobs skip the
next tick (``skipped: "prev_still_running"``) rather than queueing —
this is cron semantics, not a job queue. SIGHUP re-reads ``cron.yaml``.
SIGTERM / SIGINT drain in-flight workers up to a short grace and then
exit. No external deps beyond stdlib + pyyaml (already in
``pyproject.toml``).

Why not ``schedule`` / ``APScheduler``?
Neither is in our dep set; ``threading.Timer`` + monotonic comparisons
is ~100 lines and avoids carrying a scheduler dep into the hub
container. The job count here is small (4-6 jobs) so sophistication
doesn't earn its keep.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import signal
import subprocess
import threading
import time
from dataclasses import asdict
from pathlib import Path

from scitex_orochi._cron._config import (
    CronConfig,
    Job,
    default_log_dir,
    default_pid_path,
    default_state_path,
    load_config,
)
from scitex_orochi._cron._state import (
    CronState,
    JobRun,
    JobState,
    state_write,
)

logger = logging.getLogger("orochi.cron")

_STDOUT_TAIL_BYTES = 2048
_STDERR_TAIL_BYTES = 2048


class CronDaemon:
    """Long-running scheduler. Run via ``daemon.run()``."""

    def __init__(
        self,
        config_path: Path | None = None,
        state_path: Path | None = None,
        pid_path: Path | None = None,
        log_dir: Path | None = None,
        dry_run: bool = False,
    ) -> None:
        self.config_path = config_path
        self.state_path = state_path or default_state_path()
        self.pid_path = pid_path or default_pid_path()
        self.log_dir = log_dir or default_log_dir()
        self.dry_run = dry_run

        self._config: CronConfig | None = None
        self._stop_event = threading.Event()
        self._reload_event = threading.Event()
        self._state_lock = threading.Lock()
        self._state = CronState(
            daemon_pid=os.getpid(),
            daemon_started_at=time.time(),
        )
        # Track in-flight worker threads so we can drain on shutdown
        # and so concurrent-run-guard knows a previous tick's child is
        # still alive.
        self._workers: dict[str, threading.Thread] = {}
        self._workers_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Config handling
    # ------------------------------------------------------------------

    def load(self) -> None:
        """(Re-)read cron.yaml and rebuild the state skeleton.

        Preserves each job's ``last_run`` record so operators see
        history across reloads. New jobs start with empty history.
        Removed jobs are dropped — their state file entry disappears
        so ``cron list`` doesn't show stale rows.
        """
        self._config = load_config(self.config_path)
        now = time.time()
        # Stagger initial runs so we don't fire everything at startup.
        # Each job gets scheduled at now + min(1s, its interval) — small
        # enough to feel immediate but large enough that a 0-interval
        # misconfig can't runaway (parse_interval already rejects <=0).
        with self._state_lock:
            existing = {j.name: j for j in self._state.jobs}
            new_states: list[JobState] = []
            for job in self._config.jobs:
                prev = existing.get(job.name)
                js = JobState(
                    name=job.name,
                    interval_seconds=job.interval_seconds,
                    command=job.command,
                    timeout_seconds=job.timeout_seconds,
                    disabled=job.disabled,
                    next_run_at=(prev.next_run_at if prev else now + 1.0),
                    running=(prev.running if prev else False),
                    last_run=(prev.last_run if prev else JobRun()),
                )
                new_states.append(js)
            self._state.jobs = new_states
        self._persist_state()
        logger.info(
            "cron: loaded %d job(s) from %s",
            len(self._config.jobs),
            self.config_path or "<default>",
        )

    def _persist_state(self) -> None:
        with self._state_lock:
            state_write(self._state, self.state_path)

    # ------------------------------------------------------------------
    # PID file
    # ------------------------------------------------------------------

    def _write_pid(self) -> None:
        self.pid_path.parent.mkdir(parents=True, exist_ok=True)
        self.pid_path.write_text(str(os.getpid()), encoding="utf-8")

    def _remove_pid(self) -> None:
        try:
            current = self.pid_path.read_text(encoding="utf-8").strip()
        except OSError:
            return
        if current == str(os.getpid()):
            try:
                self.pid_path.unlink()
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Scheduling loop
    # ------------------------------------------------------------------

    def run(self) -> int:
        """Enter the scheduling loop. Blocks until SIGTERM/SIGINT."""
        self.load()
        self._write_pid()
        self._install_signal_handlers()
        logger.info("cron: daemon started (pid=%d)", os.getpid())
        try:
            while not self._stop_event.is_set():
                if self._reload_event.is_set():
                    self._reload_event.clear()
                    try:
                        self.load()
                    except Exception as exc:  # noqa: BLE001
                        logger.error("cron: reload failed — %s", exc)
                self._tick()
                tick = (self._config.tick_seconds if self._config else 10)
                self._stop_event.wait(timeout=tick)
        finally:
            self._drain_workers()
            self._remove_pid()
            logger.info("cron: daemon exited")
        return 0

    def _tick(self) -> None:
        """Fire every job whose ``next_run_at`` has passed."""
        now = time.time()
        with self._state_lock:
            due: list[JobState] = [
                js for js in self._state.jobs if js.next_run_at <= now and not js.disabled
            ]
        for js in due:
            self._dispatch(js, now)

    def _dispatch(self, js: JobState, now: float) -> None:
        """Start a worker thread for ``js`` unless a previous run is still alive.

        Concurrent-run-guard: if a worker for this job is still in
        ``_workers`` and alive, record a skip and move the next-run
        time forward by one interval. This is the cron semantic —
        never stack duplicate runs of the same job.
        """
        with self._workers_lock:
            prev = self._workers.get(js.name)
            if prev is not None and prev.is_alive():
                with self._state_lock:
                    js.last_run = JobRun(
                        orochi_started_at=now,
                        ended_at=now,
                        duration_seconds=0.0,
                        exit_code=None,
                        skipped="prev_still_running",
                        stdout_tail="",
                        stderr_tail="",
                    )
                    # Don't wait forever — reschedule for the next
                    # cadence so the next probe still happens on time.
                    js.next_run_at = now + js.interval_seconds
                self._persist_state()
                self._log_run(js.name, asdict(js.last_run))
                return
            thread = threading.Thread(
                target=self._run_job,
                name=f"cron-{js.name}",
                args=(js.name,),
                daemon=True,
            )
            self._workers[js.name] = thread
            thread.start()

    def _lookup(self, name: str) -> tuple[Job, JobState] | None:
        if self._config is None:
            return None
        for j in self._config.jobs:
            if j.name == name:
                with self._state_lock:
                    for js in self._state.jobs:
                        if js.name == name:
                            return (j, js)
        return None

    def _run_job(self, name: str) -> None:
        """Worker-thread entry — executes one job and records the outcome."""
        lookup = self._lookup(name)
        if lookup is None:
            logger.warning("cron: job %s vanished during dispatch", name)
            return
        job, js = lookup
        start = time.time()
        with self._state_lock:
            js.running = True
        self._persist_state()

        run = JobRun(orochi_started_at=start)
        try:
            if self.dry_run:
                logger.info("cron[dry-run]: would run %s -> %s", name, job.command)
                run.exit_code = 0
                run.stdout_tail = f"[dry-run] {job.command}"
            else:
                run = self._execute(job, start)
        except Exception as exc:  # noqa: BLE001
            # An internal scheduling error is distinct from the job
            # itself failing — record it as exit_code=None + skipped=
            # "internal_error:<msg>" so operators can tell them apart.
            run.ended_at = time.time()
            run.duration_seconds = run.ended_at - start
            run.exit_code = None
            run.skipped = f"internal_error:{exc}"
        finally:
            with self._state_lock:
                js.running = False
                js.last_run = run
                js.next_run_at = max(start + js.interval_seconds, time.time() + 1.0)
            self._persist_state()
            self._log_run(name, asdict(run))
            with self._workers_lock:
                # Only clear the slot if it's still us — a later dispatch
                # may have already replaced it (shouldn't happen with
                # the run-guard, but defensive).
                current = self._workers.get(name)
                if current is threading.current_thread():
                    self._workers.pop(name, None)

    def _execute(self, job: Job, start: float) -> JobRun:
        """Actually fork + run the command. Returns a populated ``JobRun``."""
        # Use shell=False with shlex.split so simple commands don't need a
        # shell, but fall back to shell=True when shlex fails (complex
        # pipelines, redirects). Operators who write pipelines knowingly
        # opt into the shell; simple commands stay safer.
        try:
            argv = shlex.split(job.command)
            shell = False
        except ValueError:
            argv = job.command
            shell = True
        try:
            proc = subprocess.run(
                argv,
                shell=shell,
                capture_output=True,
                text=True,
                timeout=job.timeout_seconds,
                env=os.environ.copy(),
            )
            exit_code = proc.returncode
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            skipped = ""
        except subprocess.TimeoutExpired as exc:
            exit_code = None
            stdout = (exc.stdout or b"") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = (exc.stderr or b"") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            skipped = f"timeout_after_{job.timeout_seconds}s"
        except FileNotFoundError as exc:
            exit_code = 127
            stdout = ""
            stderr = f"command not found: {exc}"
            skipped = ""
        end = time.time()
        return JobRun(
            orochi_started_at=start,
            ended_at=end,
            duration_seconds=end - start,
            exit_code=exit_code,
            skipped=skipped,
            stdout_tail=stdout[-_STDOUT_TAIL_BYTES:],
            stderr_tail=stderr[-_STDERR_TAIL_BYTES:],
        )

    def _log_run(self, name: str, record: dict) -> None:
        """Append one NDJSON line to the per-job log."""
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log_path = self.log_dir / f"{name}.ndjson"
            payload = {"job": name, **record}
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, default=str) + "\n")
        except OSError as exc:
            logger.warning("cron: failed to write log for %s: %s", name, exc)

    # ------------------------------------------------------------------
    # One-shot runner (used by `cron run <name>`)
    # ------------------------------------------------------------------

    def run_once(self, name: str) -> JobRun:
        """Execute a single job synchronously and return its ``JobRun``.

        Used by the CLI's ``cron run <name>``. Doesn't go through the
        scheduling loop so it works even if the daemon isn't running
        (operators can test a command change before reload).
        """
        if self._config is None:
            self._config = load_config(self.config_path)
        job = next((j for j in self._config.jobs if j.name == name), None)
        if job is None:
            raise KeyError(f"no such job: {name}")
        start = time.time()
        if self.dry_run:
            return JobRun(
                orochi_started_at=start,
                ended_at=start,
                duration_seconds=0.0,
                exit_code=0,
                skipped="",
                stdout_tail=f"[dry-run] {job.command}",
                stderr_tail="",
            )
        return self._execute(job, start)

    # ------------------------------------------------------------------
    # Signals + shutdown
    # ------------------------------------------------------------------

    def _install_signal_handlers(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_stop)
        signal.signal(signal.SIGINT, self._handle_stop)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, self._handle_reload)

    def _handle_stop(self, *_args) -> None:
        logger.info("cron: stop signal received")
        self._stop_event.set()

    def _handle_reload(self, *_args) -> None:
        logger.info("cron: reload signal received")
        self._reload_event.set()

    def _drain_workers(self, grace_seconds: float = 5.0) -> None:
        """Wait briefly for workers; they're daemon threads so the process
        can exit even if a command is mid-flight."""
        deadline = time.time() + grace_seconds
        with self._workers_lock:
            threads = list(self._workers.values())
        for t in threads:
            remaining = max(0.0, deadline - time.time())
            t.join(timeout=remaining)
