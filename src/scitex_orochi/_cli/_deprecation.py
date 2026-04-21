"""Deprecation plumbing for the CLI noun-verb refactor (Phase 1d).

This module provides the **infrastructure** Step B+C will call. No actual
renames happen in Step A — the emitters here are not yet wired into the
command tree. They exist now so that the convention doc, tests, and help
layer are self-consistent.

Two styles of notice are supported:

1. **Hard rename error** (``hard_rename_error``): a renamed command is
   called. Per the Q1 decision in the plan doc, there is **no grace
   period**. We print a single stderr line and exit with a non-zero
   code. This is terminal, not a warning.

2. **Soft one-time-per-shell notice** (``soft_notice``): for non-rename
   drifts (e.g. "this flag's semantics shifted — here's the new spelling").
   Shown at most once per (shell-session, command-name) tuple, tracked via
   a marker file under ``$XDG_STATE_HOME/scitex-orochi/deprecation/``.

Both paths honour ``SCITEX_OROCHI_NO_DEPRECATION=1`` as a hard opt-out.
"""

from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path

__all__ = [
    "ENV_OPT_OUT",
    "SOFT_TTL_S",
    "is_opted_out",
    "hard_rename_error",
    "make_rename_stub",
    "soft_notice",
    "reset_soft_notice_state",
]

ENV_OPT_OUT = "SCITEX_OROCHI_NO_DEPRECATION"

#: One-time semantics expire after this many seconds so long-running
#: shells eventually see the note again (once per day).
SOFT_TTL_S: int = 24 * 3600


def is_opted_out(env: os._Environ[str] | dict[str, str] | None = None) -> bool:
    """Return True iff the opt-out env var is set to a truthy value."""
    source: dict[str, str] | os._Environ[str]
    source = os.environ if env is None else env
    raw = source.get(ENV_OPT_OUT, "")
    return raw.lower() in {"1", "true", "yes", "on"}


def _state_dir() -> Path:
    """Return the directory where one-time-per-shell markers live."""
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "scitex-orochi" / "deprecation"


def _session_key() -> str:
    """Key that identifies the current shell session.

    Falls back to ``$PPID`` (parent PID = login shell on POSIX) so two
    subsequent CLI invocations from the same shell share state. If
    ``$SCITEX_OROCHI_SHELL_SESSION`` is set we prefer it (explicit wins).
    """
    key = os.environ.get("SCITEX_OROCHI_SHELL_SESSION")
    if key:
        return key
    return f"ppid-{os.getppid()}"


def _marker_path(command: str) -> Path:
    """Return the marker file path for ``(session, command)`` tuple."""
    h = hashlib.sha1(
        f"{_session_key()}::{command}".encode("utf-8"), usedforsecurity=False
    ).hexdigest()[:20]
    return _state_dir() / f"{h}.marker"


def _marker_fresh(path: Path, ttl_s: int) -> bool:
    """True iff the marker exists and is younger than ``ttl_s`` seconds."""
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return (time.time() - mtime) < ttl_s


def _touch_marker(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        os.utime(path, None)
    except OSError:
        # If we can't write a marker, silently accept: the worst case is
        # we emit the note again next invocation, which is acceptable.
        pass


# ---------------------------------------------------------------------------
# Emitters
# ---------------------------------------------------------------------------


def hard_rename_error(
    old_name: str,
    new_name: str,
    *,
    exit_code: int = 2,
    stream=None,
    exit_func=None,
) -> None:
    """Print the one-line rename error to stderr and exit non-zero.

    If ``SCITEX_OROCHI_NO_DEPRECATION=1`` is set, we still print the error
    (the command has been renamed — a misspelling cannot succeed just
    because the operator asked for quiet) but we do not re-emit it.

    Format (per msg#16533):
        ``error: `scitex-orochi <old>` was renamed to `scitex-orochi <new>`.``
    """
    out = sys.stderr if stream is None else stream
    exit_fn = sys.exit if exit_func is None else exit_func
    msg = (
        f"error: `scitex-orochi {old_name}` was renamed to "
        f"`scitex-orochi {new_name}`."
    )
    print(msg, file=out)
    exit_fn(exit_code)


def make_rename_stub(old_name: str, new_name: str):
    """Return a click.Command that fires :func:`hard_rename_error` when invoked.

    Used by the top-level ``_main.py`` to replace legacy flat commands
    whose body has been migrated under a noun group (Phase 1d Step C, plan
    PR #337). The stub:

    * accepts arbitrary extra args (so users who run
      ``scitex-orochi list-agents --json`` still see the rename error,
      not a click usage error that would confuse them further);
    * prints the canonical one-liner to stderr and exits ``2`` unchanged;
    * exposes a short help string mentioning the new form, so
      ``scitex-orochi --help`` readers see the redirect target.

    The stub is deliberately a ``click.Command`` (not a group) — any
    former subcommand path (e.g. ``scitex-orochi deploy stable``) is
    swallowed by ``UNPROCESSED`` and the user still gets the rename
    error. This is simpler than enumerating every old sub-verb and is
    correct per the plan: the old path is dead, not re-routed.
    """
    import click as _click

    short_help = f"Renamed -- use `scitex-orochi {new_name}`."

    @_click.command(
        old_name,
        short_help=short_help,
        help=(
            f"Renamed. Use `scitex-orochi {new_name}` instead. This stub "
            f"exists only to give a clear error message; invoking it "
            f"exits non-zero."
        ),
        # Accept any extra args so users who ran the old form with its
        # old options still hit the rename error (not a click parse error).
        context_settings={
            "ignore_unknown_options": True,
            "allow_extra_args": True,
            "help_option_names": ["-h", "--help"],
        },
    )
    @_click.argument("_args", nargs=-1, type=_click.UNPROCESSED)
    def _stub(_args):  # pragma: no cover - exercised via tests
        hard_rename_error(old_name, new_name)

    return _stub


def soft_notice(
    command: str,
    message: str,
    *,
    stream=None,
    ttl_s: int = SOFT_TTL_S,
) -> bool:
    """Emit a single-line soft deprecation note to stderr at most once per
    shell session (per ``command``).

    Returns True iff the note was actually printed this invocation. Tests
    use the return value to assert one-time-per-shell semantics.
    """
    if is_opted_out():
        return False
    marker = _marker_path(command)
    if _marker_fresh(marker, ttl_s):
        return False
    out = sys.stderr if stream is None else stream
    print(f"note: {message}", file=out)
    _touch_marker(marker)
    return True


def reset_soft_notice_state() -> None:
    """Remove all soft-notice markers for the current session. Intended
    for tests and diagnostic tooling."""
    d = _state_dir()
    if not d.is_dir():
        return
    for p in d.glob("*.marker"):
        try:
            p.unlink()
        except OSError:
            pass
