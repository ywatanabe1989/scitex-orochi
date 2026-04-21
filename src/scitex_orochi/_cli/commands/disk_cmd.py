"""``scitex-orochi disk {reaper-dry-run,pressure-probe}`` subcommands.

Ports ``scripts/client/disk-reaper.sh`` and
``scripts/client/fleet-watch/disk-pressure-probe.sh``.

``reaper-dry-run``  List/reap known-safe caches (Chrome code_sign_clone,
                    Xcode DerivedData, iOS DeviceSupport, ``claude-tmp``,
                    ...). Default mode is dry-run; ``--yes`` reaps.

``pressure-probe``  Emit an NDJSON line describing root-fs headroom, with
                    an exit code carrying the severity so cron /
                    fleet_watch.sh can trip advisories.
"""

from __future__ import annotations

import glob
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import click

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _du_kib(path: Path) -> int:
    """Return ``du -sk`` size in KiB; 0 for missing/unreadable paths."""
    if not path.exists():
        return 0
    try:
        proc = subprocess.run(
            ["du", "-sk", "--", str(path)],
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 0
    if proc.returncode != 0 or not proc.stdout.strip():
        return 0
    try:
        return int(proc.stdout.split()[0])
    except (ValueError, IndexError):
        return 0


def _human_size(kib: int) -> str:
    if kib >= 1048576:
        return f"{kib / 1048576:.1f}G"
    if kib >= 1024:
        return f"{kib / 1024:.1f}M"
    return f"{kib}K"


# ---------------------------------------------------------------------------
# Reaper target registry
# ---------------------------------------------------------------------------

@dataclass
class ReapTarget:
    name: str
    category: str  # safe-default | opt-in | never-auto
    description: str
    finder: Callable[[], list[Path]] = field(default=list)


def _find_glob(pattern: str) -> list[Path]:
    return [Path(p) for p in glob.glob(pattern)]


def _find_mtime_older(root: Path, days: int, maxdepth: int = 1) -> list[Path]:
    """Return children of ``root`` older than ``days`` days (mtime)."""
    if not root.is_dir():
        return []
    cutoff = datetime.now().timestamp() - days * 86400
    out: list[Path] = []
    # Only support maxdepth of 1 or 2 per the targets we care about.
    candidates: list[Path] = []
    try:
        for child in root.iterdir():
            candidates.append(child)
    except OSError:
        return []
    if maxdepth >= 2:
        # Another level down
        extra: list[Path] = []
        for c in list(candidates):
            if c.is_dir():
                try:
                    extra.extend(c.iterdir())
                except OSError:
                    continue
        candidates.extend(extra)
    for p in candidates:
        try:
            if p.stat().st_mtime < cutoff:
                out.append(p)
        except OSError:
            continue
    return out


def _find_dir_children(root: Path, maxdepth: int = 1) -> list[Path]:
    if not root.is_dir():
        return []
    try:
        return [c for c in root.iterdir()]
    except OSError:
        return []


def _build_targets() -> list[ReapTarget]:
    uid = os.environ.get("UID") or str(os.getuid())
    home = Path.home()
    return [
        ReapTarget(
            "chrome-code-sign-clone",
            "safe-default",
            "macOS Chrome codesign cache leak — regenerates on next launch",
            lambda: _find_glob(
                "/private/var/folders/*/*/X/com.google.Chrome.code_sign_clone"
            ),
        ),
        ReapTarget(
            "claude-tmp-stale",
            "safe-default",
            "Claude Code tool-output dirs older than 2d — stale session artefacts",
            lambda: _find_mtime_older(
                Path(f"/private/tmp/claude-{uid}"), days=2,
            ),
        ),
        ReapTarget(
            "ios-device-support",
            "safe-default",
            "Xcode iOS DeviceSupport older than 30d — regenerates",
            lambda: _find_mtime_older(
                home / "Library/Developer/Xcode/iOS DeviceSupport",
                days=30,
            ),
        ),
        ReapTarget(
            "xcode-derived-data",
            "safe-default",
            "Xcode DerivedData — rebuilds on next Xcode build",
            lambda: _find_dir_children(
                home / "Library/Developer/Xcode/DerivedData",
            ),
        ),
        ReapTarget(
            "core-simulator-caches",
            "safe-default",
            "CoreSimulator caches — regenerate",
            lambda: _find_dir_children(
                home / "Library/Developer/CoreSimulator/Caches",
                maxdepth=2,
            ),
        ),
        ReapTarget(
            "gradle-caches",
            "opt-in",
            "Gradle caches — regenerate on next build (multi-minute first-build cost)",
            lambda: [home / ".gradle/caches", home / ".gradle/daemon"],
        ),
        ReapTarget(
            "npm-cache",
            "opt-in",
            "npm cache — regenerates on next install",
            lambda: [home / ".npm/_cacache"],
        ),
        ReapTarget(
            "bun-install-cache",
            "opt-in",
            "bun install cache — regenerates",
            lambda: [home / ".bun/install/cache"],
        ),
        ReapTarget(
            "trash",
            "never-auto",
            "User Trash — emptying is a user decision",
            lambda: [home / ".Trash"],
        ),
        ReapTarget(
            "downloads-note",
            "never-auto",
            "~/Downloads is user data; not touched by this script",
            list,
        ),
    ]


# ---------------------------------------------------------------------------
# Group
# ---------------------------------------------------------------------------

@click.group("disk")
def disk() -> None:
    """Disk-hygiene utilities (reaper, pressure probe)."""


# ---------------------------------------------------------------------------
# disk reaper-dry-run
# ---------------------------------------------------------------------------

@disk.command("reaper-dry-run")
@click.option("--yes", "-y", "yes", is_flag=True, help="Actually reap (default is dry-run).")
@click.option("--dry-run", "dry_run_flag", is_flag=True, help="Explicit dry-run.")
@click.option("--only", default=None, help="Process only this target name.")
@click.option(
    "--include",
    "includes",
    multiple=True,
    help="Opt-in target to include (repeatable).",
)
@click.option("--list", "do_list", is_flag=True, help="List targets and exit.")
def reaper_dry_run(
    yes: bool,
    dry_run_flag: bool,
    only: str | None,
    includes: tuple[str, ...],
    do_list: bool,
) -> None:
    """List/reap known-safe caches. Dry-run unless ``--yes`` is passed.

    Equivalent to ``scripts/client/disk-reaper.sh`` (``--yes`` overrides
    ``--dry-run`` for flag-mutex parity).
    """
    del dry_run_flag
    dry_run = not yes
    host = platform.node()
    os_name = platform.system()
    targets = _build_targets()

    if do_list:
        click.echo(f"{'name':<26}  {'category':<13}  description")
        click.echo(f"{'----':<26}  {'--------':<13}  -----------")
        for t in targets:
            click.echo(f"{t.name:<26}  {t.category:<13}  {t.description}")
        return

    def _should_process(t: ReapTarget) -> bool:
        if only:
            return t.name == only
        if t.category == "safe-default":
            return True
        if t.category == "opt-in":
            return t.name in includes
        return False

    mode = "dry-run" if dry_run else "REAP"
    click.echo(f"# disk-reaper on {host} ({os_name}) — mode={mode}")
    click.echo(
        f"{'name':<26}  {'category':<13}  {'size':>10}  description"
    )
    click.echo(
        f"{'----':<26}  {'--------':<13}  {'----':>10}  -----------"
    )
    total_kib = 0
    reaped_any = False
    for t in targets:
        try:
            paths = t.finder()
        except Exception:  # noqa: BLE001 - one flaky finder shouldn't abort
            paths = []
        paths = [p for p in paths if p.exists()]
        kib = sum(_du_kib(p) for p in paths)
        click.echo(
            f"{t.name:<26}  {t.category:<13}  {_human_size(kib):>10}  {t.description}"
        )
        if not _should_process(t):
            continue
        if dry_run:
            for p in paths:
                click.echo(f"    (dry-run) would rm -rf {p}")
            continue
        if not paths:
            continue
        for p in paths:
            try:
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)
                click.echo(f"    reaped: {p}")
            except OSError as exc:
                click.echo(f"    reap-failed: {p} ({exc})", err=True)
                continue
        reaped_any = True
        total_kib += kib

    if dry_run:
        click.echo(
            "\n# dry-run complete. Re-run with --yes to reap safe-default targets."
        )
        click.echo(
            "# Use --include <name> to add opt-in targets (e.g. --include gradle-caches)."
        )
        return
    if reaped_any:
        click.echo(f"\n# reaped ~{_human_size(total_kib)} total. Disk state after:")
        try:
            proc = subprocess.run(
                ["df", "-h", "/"], capture_output=True, text=True, timeout=5
            )
            for line in proc.stdout.splitlines()[:2]:
                click.echo(line)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    else:
        click.echo("\n# nothing reaped (empty targets).")


# ---------------------------------------------------------------------------
# disk pressure-probe
# ---------------------------------------------------------------------------

@disk.command("pressure-probe")
@click.option(
    "--advisory-gib",
    type=int,
    default=int(os.environ.get("DISK_FREE_ADVISORY_GIB", "10")),
    show_default=True,
)
@click.option(
    "--warn-gib",
    type=int,
    default=int(os.environ.get("DISK_FREE_WARN_GIB", "5")),
    show_default=True,
)
@click.option(
    "--critical-gib",
    type=int,
    default=int(os.environ.get("DISK_FREE_CRITICAL_GIB", "2")),
    show_default=True,
)
@click.option(
    "--out-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Append NDJSON to ``<out>/disk-pressure-<host>.ndjson`` [env HOST_TELEMETRY_OUT_DIR].",
)
def pressure_probe(
    advisory_gib: int,
    warn_gib: int,
    critical_gib: int,
    out_dir: Path | None,
) -> None:
    """Probe root-fs headroom and emit an NDJSON advisory."""
    host = platform.node().split(".")[0]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out_dir = out_dir or Path(
        os.environ.get("HOST_TELEMETRY_OUT_DIR")
        or Path.home() / ".scitex/orochi/host-telemetry"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"disk-pressure-{host}.ndjson"

    try:
        proc = subprocess.run(
            ["df", "-k", "/"], capture_output=True, text=True, timeout=5
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        record = {
            "schema": "scitex-orochi/disk-pressure-probe/v1",
            "host": host,
            "ts": ts,
            "error": "df_failed",
        }
        _append(out_file, record)
        sys.exit(3)
    lines = proc.stdout.splitlines()
    if len(lines) < 2:
        _append(
            out_file,
            {
                "schema": "scitex-orochi/disk-pressure-probe/v1",
                "host": host, "ts": ts, "error": "df_failed",
            },
        )
        sys.exit(3)
    parts = lines[1].split()
    try:
        total_kib = int(parts[1])
        used_kib = int(parts[2])
        avail_kib = int(parts[3])
    except (ValueError, IndexError):
        _append(
            out_file,
            {
                "schema": "scitex-orochi/disk-pressure-probe/v1",
                "host": host, "ts": ts, "error": "df_parse_failed",
            },
        )
        sys.exit(3)

    total_gib = total_kib // 1048576
    used_gib = used_kib // 1048576
    avail_gib = avail_kib // 1048576

    if avail_gib < critical_gib:
        severity, exit_code = "critical", 3
    elif avail_gib < warn_gib:
        severity, exit_code = "warn", 2
    elif avail_gib < advisory_gib:
        severity, exit_code = "advisory", 1
    else:
        severity, exit_code = "ok", 0

    # Top consumers (best-effort).
    home = Path.home()
    top_rows: list[dict[str, str]] = []
    for p in [
        home / ".gradle",
        home / ".android",
        home / "Downloads",
        home / ".colima",
        home / "Library" / "Caches",
    ]:
        if not p.exists():
            continue
        try:
            r = subprocess.run(
                ["du", "-sh", "--", str(p)],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0 and r.stdout.strip():
                parts = r.stdout.split(None, 1)
                if len(parts) == 2:
                    top_rows.append(
                        {"size": parts[0], "path": parts[1].rstrip()}
                    )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    record = {
        "schema": "scitex-orochi/disk-pressure-probe/v1",
        "host": host,
        "ts": ts,
        "mount": "/",
        "total_gib": total_gib,
        "used_gib": used_gib,
        "avail_gib": avail_gib,
        "severity": severity,
        "thresholds": {
            "advisory_gib": advisory_gib,
            "warn_gib": warn_gib,
            "critical_gib": critical_gib,
        },
        "top_home_consumers": top_rows,
    }
    _append(out_file, record)
    click.echo(json.dumps(record, separators=(",", ":"), sort_keys=False))
    if severity != "ok":
        click.echo(
            f"disk-pressure {severity} on {host}: / has {avail_gib} GiB free "
            f"(of {total_gib} GiB). Thresholds: advisory<{advisory_gib} "
            f"warn<{warn_gib} critical<{critical_gib}. Run "
            f"'scitex-orochi disk reaper-dry-run' to see reapable targets.",
            err=True,
        )
    sys.exit(exit_code)


def _append(path: Path, record: dict) -> None:
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
    except OSError:
        # Best effort — don't crash the probe because the log's immutable.
        pass


__all__ = ["disk"]
