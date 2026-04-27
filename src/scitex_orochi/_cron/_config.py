"""Config schema + YAML loader for the Orochi unified cron daemon.

Responsibilities
----------------
* Parse ``~/.scitex/orochi/cron.yaml`` (or an explicit path).
* Expand ``${VAR}`` placeholders in command strings against a merged env
  (process env + a small set of daemon-injected defaults like
  ``SCITEX_OROCHI_REPO_ROOT``). Unknown vars are left untouched so
  errors surface at job-run time rather than silently becoming empty
  strings.
* Convert human-friendly interval strings (``"5m"``, ``"1h"``,
  ``"30s"``) into seconds.

No scheduler logic lives here — that's ``_daemon.py``. Keeping the
parser isolated makes the YAML easy to unit-test without a live daemon.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ----------------------------------------------------------------------
# Paths — the daemon, the CLI, and the heartbeat pusher all agree on
# these locations so "what the daemon thinks it did" and "what
# `scitex-orochi cron list` reports" can never diverge.
# ----------------------------------------------------------------------


def default_config_path() -> Path:
    """Location of ``cron.yaml`` (operator-owned, per-host)."""
    return Path.home() / ".scitex" / "orochi" / "cron.yaml"


def default_state_path() -> Path:
    """Location of the daemon's JSON state file.

    Follows the same convention as other Orochi client-side state
    (``~/.local/state/scitex/...``). Kept outside ``~/.scitex/orochi/``
    because it's orochi_runtime telemetry, not config.
    """
    return Path.home() / ".local" / "state" / "scitex" / "orochi-cron" / "state.json"


def default_log_dir() -> Path:
    """Per-job stdout/stderr NDJSON log directory."""
    return Path.home() / ".local" / "state" / "scitex" / "orochi-cron" / "logs"


def default_pid_path() -> Path:
    """PID file for the daemon — used by ``cron status`` to answer
    "is the daemon loaded, and what PID?" without speaking launchctl."""
    return Path.home() / ".local" / "state" / "scitex" / "orochi-cron" / "daemon.pid"


# ----------------------------------------------------------------------
# Interval parser
# ----------------------------------------------------------------------

_INTERVAL_RE = re.compile(r"^\s*(\d+)\s*([smhd]?)\s*$", re.IGNORECASE)
_INTERVAL_MULTIPLIERS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_interval(value: str | int | float) -> int:
    """Convert ``"5m"`` / ``"1h"`` / ``"30s"`` / plain seconds to int seconds.

    Accepts:
        * ``int`` / ``float`` — treated as seconds.
        * ``"<N><unit>"`` where unit is ``s|m|h|d`` (default ``s``).
    Raises ``ValueError`` on unparseable input so the daemon crashes
    visibly at YAML-load time rather than silently defaulting.
    """
    if isinstance(value, (int, float)):
        seconds = int(value)
        if seconds <= 0:
            raise ValueError(f"interval must be positive, got {value!r}")
        return seconds
    if not isinstance(value, str):
        raise ValueError(f"interval must be int or string, got {type(value).__name__}")
    match = _INTERVAL_RE.match(value)
    if not match:
        raise ValueError(f"unparseable interval: {value!r}")
    n = int(match.group(1))
    unit = match.group(2).lower()
    seconds = n * _INTERVAL_MULTIPLIERS[unit]
    if seconds <= 0:
        raise ValueError(f"interval must be positive, got {value!r}")
    return seconds


# ----------------------------------------------------------------------
# Variable expansion — intentionally narrow so typos don't silently
# evaluate to empty strings.
# ----------------------------------------------------------------------

_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand_vars(template: str, env: dict[str, str]) -> str:
    """Replace ``${NAME}`` with ``env[NAME]``; leave unknown names as-is.

    The leave-as-is behavior is intentional: if an operator writes
    ``${REPO_ROOOT}`` (typo), we'd rather the subprocess fail loudly
    with "no such command" than silently run "``bash ``" which would
    tie up a job slot doing nothing.
    """

    def _sub(m: re.Match[str]) -> str:
        name = m.group(1)
        return env.get(name, m.group(0))

    return _VAR_RE.sub(_sub, template)


# ----------------------------------------------------------------------
# Dataclasses
# ----------------------------------------------------------------------


@dataclass
class Job:
    """One scheduled job.

    Attributes
    ----------
    name:
        Unique identifier. Used as the key in state + log file names.
    interval_seconds:
        Cadence in seconds (resolved from ``interval`` in YAML).
    command:
        Shell command line. ``${VAR}`` placeholders are pre-expanded
        against the daemon's merged env when the config is loaded.
    timeout_seconds:
        Per-job wall-clock timeout. Defaults to 600s (10 min).
    disabled:
        Operator-set kill switch. Disabled jobs still appear in
        ``cron list`` so they can be re-enabled without editing YAML.
    """

    name: str
    interval_seconds: int
    command: str
    timeout_seconds: int = 600
    disabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "interval": self.interval_seconds,
            "command": self.command,
            "timeout": self.timeout_seconds,
            "disabled": self.disabled,
        }


@dataclass
class CronConfig:
    """Parsed ``cron.yaml`` — a set of jobs plus daemon-level knobs.

    ``tick_seconds`` is how often the scheduler wakes to check due
    jobs. Keep it smaller than the shortest interval so cadence drift
    stays bounded. Default 10s — negligible CPU, and even 1m jobs are
    fired within 10s of their due time.
    """

    jobs: list[Job] = field(default_factory=list)
    tick_seconds: int = 10


# ----------------------------------------------------------------------
# Loader
# ----------------------------------------------------------------------


def _auto_repo_root() -> str:
    """Best-effort resolution of ``SCITEX_OROCHI_REPO_ROOT``.

    Priority:
      1. Explicit ``SCITEX_OROCHI_REPO_ROOT`` in the env.
      2. The installed ``scitex_orochi`` package location + walk up
         until we find a ``pyproject.toml`` naming scitex-orochi. This
         matches the stable-bin-path shape from PR #326 so a
         feature-branch worktree doesn't 404 a scheduler after merge.
      3. Empty string — unresolved ``${SCITEX_OROCHI_REPO_ROOT}``
         tokens are then left visible in the command so the failure
         mode is obvious.
    """
    env = os.environ.get("SCITEX_OROCHI_REPO_ROOT")
    if env:
        return env
    try:
        import scitex_orochi  # type: ignore  # noqa: F401 — just need the path

        pkg_path = Path(scitex_orochi.__file__).resolve().parent
    except Exception:
        return ""
    # Walk up until we hit a pyproject.toml with scitex-orochi.
    for candidate in [pkg_path, *pkg_path.parents]:
        pyproject = candidate / "pyproject.toml"
        if pyproject.is_file():
            try:
                content = pyproject.read_text(encoding="utf-8", errors="replace")
                if 'name = "scitex-orochi"' in content:
                    return str(candidate)
            except OSError:
                continue
    return ""


def _default_env() -> dict[str, str]:
    """Minimal env the daemon injects before variable expansion.

    * Process env (so operator-set vars like ``HOME`` work).
    * ``SCITEX_OROCHI_REPO_ROOT`` auto-detected (matches the
      stable-bin-path pattern).
    """
    env = dict(os.environ)
    if not env.get("SCITEX_OROCHI_REPO_ROOT"):
        env["SCITEX_OROCHI_REPO_ROOT"] = _auto_repo_root()
    return env


def load_config(
    path: str | Path | None = None,
    *,
    env_overrides: dict[str, str] | None = None,
) -> CronConfig:
    """Parse a cron YAML file into a ``CronConfig``.

    Parameters
    ----------
    path:
        Path to ``cron.yaml``. Defaults to ``~/.scitex/orochi/cron.yaml``.
        A missing file is a hard error because silent "no jobs" would
        mask the operator forgetting to copy the example.
    env_overrides:
        Extra vars layered on top of the process env. Mainly used by
        tests to inject deterministic repo paths / ``$HOME`` stubs.

    Raises
    ------
    FileNotFoundError:
        If the YAML file is missing.
    ValueError:
        For malformed job entries, duplicate names, or unparseable
        intervals. Each error names the offending job so the operator
        can fix ``cron.yaml`` without running the daemon.
    """
    p = Path(path) if path is not None else default_config_path()
    if not p.is_file():
        raise FileNotFoundError(
            f"cron config not found: {p}\n"
            f"copy deployment/host-setup/orochi-cron/cron.yaml.example "
            f"to {p} and tune."
        )
    with p.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{p}: top-level must be a mapping, got {type(raw).__name__}")

    env = _default_env()
    if env_overrides:
        env.update(env_overrides)

    tick = int(raw.get("tick_seconds", 10))
    if tick <= 0:
        raise ValueError(f"{p}: tick_seconds must be positive, got {tick}")

    raw_jobs = raw.get("jobs", [])
    if not isinstance(raw_jobs, list):
        raise ValueError(f"{p}: 'jobs' must be a list, got {type(raw_jobs).__name__}")

    seen: set[str] = set()
    jobs: list[Job] = []
    for idx, entry in enumerate(raw_jobs):
        if not isinstance(entry, dict):
            raise ValueError(f"{p}: jobs[{idx}] must be a mapping")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{p}: jobs[{idx}] missing 'name'")
        if name in seen:
            raise ValueError(f"{p}: duplicate job name {name!r}")
        seen.add(name)
        if "interval" not in entry:
            raise ValueError(f"{p}: job {name!r} missing 'interval'")
        try:
            interval = parse_interval(entry["interval"])
        except ValueError as e:
            raise ValueError(f"{p}: job {name!r}: {e}") from None
        command = entry.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError(f"{p}: job {name!r} missing 'command'")
        command_expanded = expand_vars(command, env)
        timeout = entry.get("timeout", 600)
        try:
            timeout_seconds = parse_interval(timeout)
        except ValueError as e:
            raise ValueError(f"{p}: job {name!r} timeout: {e}") from None
        disabled = bool(entry.get("disabled", False))
        jobs.append(
            Job(
                name=name,
                interval_seconds=interval,
                command=command_expanded,
                timeout_seconds=timeout_seconds,
                disabled=disabled,
            )
        )

    return CronConfig(jobs=jobs, tick_seconds=tick)
