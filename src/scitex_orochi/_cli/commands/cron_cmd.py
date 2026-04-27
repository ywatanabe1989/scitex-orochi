"""CLI: ``scitex-orochi cron {start, stop, list, run, status, reload}``.

Manages the unified Orochi cron daemon (msg#16406 / msg#16410).

Subcommand matrix
-----------------
* ``start``   — shell out to ``install-orochi-cron.sh`` to install +
                load the OS-native unit. Idempotent.
* ``stop``    — unload only by default (daemon stays installed).
                ``--uninstall`` additionally removes the unit file so
                ``start`` will reinstall from template.
* ``list``    — JSON/text snapshot of every job: name, interval,
                last_run, last_exit, next_run, disabled. Reads the
                shared state file written by the daemon — works even
                if the daemon isn't loaded (returns last known state
                or an empty array).
* ``run``     — invoke a single job once, synchronously, and print
                its result. Doesn't go through the daemon loop, so
                it works before the daemon is installed.
* ``status``  — "is the daemon loaded + PID?" Combines the PID file
                (the daemon's own view) with ``os.kill(pid, 0)`` so
                stale PID files don't give false positives.
* ``reload``  — ``kill -HUP`` the daemon so it re-reads cron.yaml
                without a full restart.

All subcommands honour the top-level ``--json`` flag for orochi_machine
readable output; tail commands also accept explicit ``--text`` / ``--json``
overrides when the parent context is unavailable (e.g. direct imports
from other CLI entry points).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import click

from scitex_orochi._cron import (
    CronDaemon,
    default_config_path,
    default_log_dir,
    default_state_path,
    state_read,
)
from scitex_orochi._cron._config import default_pid_path
from scitex_orochi._cron._state import render_cron_jobs


def _repo_root() -> Path:
    """Climb from the installed package to the repo root.

    Mirrors the logic in ``_cron._config._auto_repo_root`` but the CLI
    needs a Path, not a string. Falls back to ``$SCITEX_OROCHI_REPO_ROOT``
    if the package isn't next to a pyproject (e.g. in a venv pip install
    from PyPI — though Phase 1 doesn't ship there).
    """
    env = os.environ.get("SCITEX_OROCHI_REPO_ROOT")
    if env:
        return Path(env)
    try:
        import scitex_orochi  # noqa: F401

        here = Path(scitex_orochi.__file__).resolve().parent
    except Exception:
        return Path.cwd()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").is_file():
            try:
                text = (candidate / "pyproject.toml").read_text(
                    encoding="utf-8", errors="replace"
                )
                if 'name = "scitex-orochi"' in text:
                    return candidate
            except OSError:
                continue
    return Path.cwd()


@click.group("cron")
def cron() -> None:
    """Manage the unified Orochi cron daemon."""


# ----------------------------------------------------------------------
# cron start
# ----------------------------------------------------------------------


@cron.command("start")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Pass --dry-run to install-orochi-cron.sh (show actions only).",
)
@click.option(
    "--no-migrate",
    is_flag=True,
    help="Skip migration of legacy per-job units.",
)
def cron_start(dry_run: bool, no_migrate: bool) -> None:
    """Install + load the cron daemon via install-orochi-cron.sh."""
    installer = _repo_root() / "scripts" / "client" / "install-orochi-cron.sh"
    if not installer.is_file():
        raise click.ClickException(
            f"installer not found: {installer} — run from a scitex-orochi checkout"
        )
    cmd = ["bash", str(installer)]
    if dry_run:
        cmd.append("--dry-run")
    if no_migrate:
        cmd.append("--no-migrate")
    click.echo(" ".join(cmd))
    rc = subprocess.call(cmd)
    sys.exit(rc)


# ----------------------------------------------------------------------
# cron stop
# ----------------------------------------------------------------------


@cron.command("stop")
@click.option(
    "--uninstall",
    is_flag=True,
    help="Also remove the unit file (so `cron start` reinstalls from template).",
)
def cron_stop(uninstall: bool) -> None:
    """Unload the cron daemon. ``--uninstall`` additionally removes the unit file."""
    installer = _repo_root() / "scripts" / "client" / "install-orochi-cron.sh"
    if uninstall:
        if not installer.is_file():
            raise click.ClickException(f"installer not found: {installer}")
        rc = subprocess.call(["bash", str(installer), "--uninstall"])
        sys.exit(rc)
    # Best-effort unload without touching the unit file.
    if sys.platform == "darwin":
        target = Path.home() / "Library/LaunchAgents/com.scitex.orochi-cron.plist"
        if target.is_file():
            rc = subprocess.call(["launchctl", "unload", str(target)])
            click.echo(f"launchctl unload {target} -> rc={rc}")
            sys.exit(0 if rc in (0,) else rc)
        click.echo("no plist loaded", err=True)
        sys.exit(0)
    # Linux: try systemd --user stop; succeed silently if not installed.
    rc = subprocess.call(
        ["systemctl", "--user", "stop", "scitex-orochi-cron.service"]
    )
    sys.exit(0 if rc == 0 else rc)


# ----------------------------------------------------------------------
# cron list
# ----------------------------------------------------------------------


@cron.command("list")
@click.option(
    "--state",
    "state_path_str",
    default=None,
    help=f"Override state file (default: {default_state_path()}).",
)
@click.pass_context
def cron_list(ctx: click.Context, state_path_str: str | None) -> None:
    """Print each job's cadence + last run outcome + next run time."""
    state_path = Path(state_path_str) if state_path_str else default_state_path()
    state = state_read(state_path)
    jobs = render_cron_jobs(state)
    as_json = bool(ctx.obj and ctx.obj.get("json"))
    if as_json:
        click.echo(json.dumps(jobs, indent=2, default=str))
        return
    if not jobs:
        click.echo("no jobs registered (daemon not running or cron.yaml empty)")
        return
    # Keep text output small + greppable.
    click.echo(f"{'job':<32} {'interval':>10} {'last':>22} {'exit':>6} {'next':>22}")
    now = time.time()
    for j in jobs:
        last = _fmt_ts(j.get("last_run"))
        nxt = _fmt_rel(j.get("next_run"), now)
        exit_code = j.get("last_exit")
        exit_s = "-" if exit_code is None else str(exit_code)
        click.echo(
            f"{j['name']:<32} {j['interval']!s:>10} {last:>22} {exit_s:>6} {nxt:>22}"
        )


def _fmt_ts(ts: float | None) -> str:
    if not ts:
        return "never"
    lt = time.localtime(float(ts))
    return time.strftime("%Y-%m-%d %H:%M:%S", lt)


def _fmt_rel(ts: float | None, now: float) -> str:
    if not ts:
        return "-"
    delta = float(ts) - now
    if delta < -60:
        return f"{int(-delta)}s ago (overdue)"
    if delta < 0:
        return "due now"
    if delta < 60:
        return f"in {int(delta)}s"
    if delta < 3600:
        return f"in {int(delta // 60)}m"
    return f"in {delta / 3600:.1f}h"


# ----------------------------------------------------------------------
# cron run
# ----------------------------------------------------------------------


@cron.command("run")
@click.argument("name")
@click.option("--dry-run", is_flag=True, help="Don't exec — print the command only.")
@click.option(
    "--config",
    "config_path",
    default=None,
    help=f"Override cron.yaml (default: {default_config_path()}).",
)
@click.pass_context
def cron_run(
    ctx: click.Context, name: str, dry_run: bool, config_path: str | None
) -> None:
    """Fire a single job once and print its outcome.

    Doesn't go through the daemon loop — you can test a new command
    before installing the daemon.
    """
    daemon = CronDaemon(
        config_path=Path(config_path) if config_path else None,
        dry_run=dry_run,
    )
    try:
        run = daemon.run_once(name)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from None
    except KeyError as exc:
        raise click.ClickException(str(exc)) from None

    payload = {
        "name": name,
        "orochi_started_at": run.orochi_started_at,
        "ended_at": run.ended_at,
        "duration_seconds": run.duration_seconds,
        "exit_code": run.exit_code,
        "skipped": run.skipped or None,
        "stdout_tail": run.stdout_tail,
        "stderr_tail": run.stderr_tail,
    }
    as_json = bool(ctx.obj and ctx.obj.get("json"))
    if as_json:
        click.echo(json.dumps(payload, indent=2, default=str))
    else:
        click.echo(f"job:      {name}")
        click.echo(f"exit:     {run.exit_code}")
        click.echo(f"duration: {run.duration_seconds:.2f}s")
        if run.skipped:
            click.echo(f"skipped:  {run.skipped}")
        if run.stdout_tail:
            click.echo("--- stdout (tail) ---")
            click.echo(run.stdout_tail)
        if run.stderr_tail:
            click.echo("--- stderr (tail) ---")
            click.echo(run.stderr_tail)
    if run.exit_code not in (0, None):
        sys.exit(run.exit_code)


# ----------------------------------------------------------------------
# cron status
# ----------------------------------------------------------------------


@cron.command("status")
@click.option(
    "--pid",
    "pid_path_str",
    default=None,
    help=f"Override PID file (default: {default_pid_path()}).",
)
@click.option(
    "--state",
    "state_path_str",
    default=None,
    help=f"Override state file (default: {default_state_path()}).",
)
@click.pass_context
def cron_status(
    ctx: click.Context,
    pid_path_str: str | None,
    state_path_str: str | None,
) -> None:
    """Report whether the daemon is running + its PID + config location."""
    pid_path = Path(pid_path_str) if pid_path_str else default_pid_path()
    state_path = Path(state_path_str) if state_path_str else default_state_path()
    pid, alive = _daemon_liveness(pid_path)
    state = state_read(state_path)
    payload = {
        "daemon_pid": pid,
        "daemon_running": alive,
        "daemon_started_at": (state.daemon_started_at if state else None),
        "state_updated_at": (state.updated_at if state else None),
        "config_path": str(default_config_path()),
        "state_path": str(state_path),
        "pid_path": str(pid_path),
        "log_dir": str(default_log_dir()),
        "job_count": len(state.jobs) if state else 0,
    }
    as_json = bool(ctx.obj and ctx.obj.get("json"))
    if as_json:
        click.echo(json.dumps(payload, indent=2, default=str))
        return
    click.echo(f"pid:      {pid if pid else '-'}")
    click.echo(f"running:  {alive}")
    click.echo(f"jobs:     {payload['job_count']}")
    click.echo(f"config:   {payload['config_path']}")
    click.echo(f"state:    {payload['state_path']}")
    click.echo(f"logs:     {payload['log_dir']}")


def _daemon_liveness(pid_path: Path) -> tuple[int, bool]:
    """Return (pid, is_alive). 0 + False if no pid file."""
    if not pid_path.is_file():
        return (0, False)
    try:
        raw = pid_path.read_text(encoding="utf-8").strip()
        pid = int(raw)
    except (OSError, ValueError):
        return (0, False)
    if pid <= 0:
        return (0, False)
    try:
        os.kill(pid, 0)
        return (pid, True)
    except ProcessLookupError:
        return (pid, False)
    except PermissionError:
        # Process exists, owned by another user — treat as alive.
        return (pid, True)


# ----------------------------------------------------------------------
# cron reload
# ----------------------------------------------------------------------


@cron.command("reload")
@click.option(
    "--pid",
    "pid_path_str",
    default=None,
    help=f"Override PID file (default: {default_pid_path()}).",
)
def cron_reload(pid_path_str: str | None) -> None:
    """Signal the daemon to re-read cron.yaml (SIGHUP)."""
    pid_path = Path(pid_path_str) if pid_path_str else default_pid_path()
    pid, alive = _daemon_liveness(pid_path)
    if not alive:
        raise click.ClickException(
            f"daemon not running (pid file: {pid_path}) — start with `scitex-orochi cron start`"
        )
    try:
        os.kill(pid, signal.SIGHUP)
    except OSError as exc:
        raise click.ClickException(f"failed to signal pid {pid}: {exc}") from None
    click.echo(f"sent SIGHUP to pid {pid}")
