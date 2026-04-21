"""``scitex-orochi chrome-watchdog check`` subcommand.

Python port of ``scripts/client/chrome-codesign-clone-watchdog.sh``.

Reaps the ``/private/var/folders/*/*/X/com.google.Chrome.code_sign_clone``
cache when it grows above ``--reap-gib`` (default 5). Logs an advisory
between ``--advise-gib`` and ``--reap-gib``. Read-only otherwise.

macOS-specific — on Linux exits ``0`` quickly with a "not applicable"
record.
"""

from __future__ import annotations

import glob
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import click


def _du_kib(path: Path) -> int | None:
    try:
        proc = subprocess.run(
            ["du", "-sk", "--", str(path)],
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return int(proc.stdout.split()[0])
    except (ValueError, IndexError):
        return None


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    click.echo(f"[{ts}] chrome-codesign-clone-watchdog: {msg}")


@click.group("chrome-watchdog")
def chrome_watchdog() -> None:
    """macOS Chrome ``code_sign_clone`` cache reaper."""


@chrome_watchdog.command("check")
@click.option(
    "--advise-gib",
    type=int,
    default=2,
    show_default=True,
    envvar="ADVISE_GIB",
    help="Log advisory when total size ≥ this (GiB).",
)
@click.option(
    "--reap-gib",
    type=int,
    default=5,
    show_default=True,
    envvar="REAP_GIB",
    help="Delete directory when total size ≥ this (GiB).",
)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    help="Report only; never delete.",
)
def check(advise_gib: int, reap_gib: int, dry_run: bool) -> None:
    """Advise/reap the Chrome codesign-clone cache. Safe on non-macOS hosts."""
    if platform.system() != "Darwin":
        _log("not macOS — no-op")
        sys.exit(0)

    candidates = [
        Path(p)
        for p in glob.glob(
            "/private/var/folders/*/*/X/com.google.Chrome.code_sign_clone"
        )
    ]
    if not candidates:
        _log("no Chrome code_sign_clone paths found — nothing to do")
        sys.exit(0)

    advise_kib = advise_gib * 1024 * 1024
    reap_kib = reap_gib * 1024 * 1024
    rc = 0
    for path in candidates:
        if not path.is_dir():
            continue
        kib = _du_kib(path)
        if kib is None:
            _log(f"ERROR: failed to size {path}")
            rc = 1
            continue
        gib = kib // 1024 // 1024
        if kib >= reap_kib:
            if dry_run:
                _log(
                    f"WOULD REAP {path} ({gib} GiB >= {reap_gib} GiB) — dry run"
                )
            else:
                _log(f"REAPING {path} ({gib} GiB >= {reap_gib} GiB)")
                try:
                    shutil.rmtree(path)
                    _log(f"reaped {path}")
                except OSError as exc:
                    _log(f"ERROR: rm -rf failed for {path}: {exc}")
                    rc = 1
        elif kib >= advise_kib:
            _log(
                f"ADVISORY {path} is {gib} GiB "
                f"(>= {advise_gib} GiB, < {reap_gib} GiB reap threshold)"
            )
        else:
            _log(f"OK {path} is {gib} GiB (< {advise_gib} GiB)")
    sys.exit(rc)


__all__ = ["chrome_watchdog"]
