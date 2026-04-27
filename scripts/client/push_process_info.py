#!/usr/bin/env python3
"""
push_process_info.py — per-host process info pusher.

Collects the running tmux sessions, screen sessions, and scitex-agent-container
systemd / launchd units for this host, and appends an NDJSON line to
~/.scitex/orochi/orochi_runtime/fleet-watch/process-info/<host>.ndjson.

Lets the hub correlate "agent registry says X is alive" against "this host
actually has X as a tmux session / systemd unit", catching registry-drift
and zombies.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _source_host() -> str:
    h = os.environ.get("SCITEX_OROCHI_HOSTNAME") or ""
    if h:
        return h
    return socket.gethostname().split(".", 1)[0]


def _tmux_sessions() -> list[dict[str, Any]]:
    try:
        out = subprocess.check_output(
            [
                "tmux",
                "list-sessions",
                "-F",
                "#{session_name}|#{session_created}|#{session_windows}|#{session_attached}",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
    except Exception:
        return []
    sessions: list[dict[str, Any]] = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) < 4:
            continue
        name, created, windows, attached = parts[0], parts[1], parts[2], parts[3]
        sessions.append(
            {
                "name": name,
                "created_ts": int(created) if created.isdigit() else None,
                "windows": int(windows) if windows.isdigit() else None,
                "attached": attached == "1",
            }
        )
    return sessions


def _screen_sessions() -> list[str]:
    try:
        out = subprocess.check_output(
            ["screen", "-ls"], text=True, stderr=subprocess.STDOUT, timeout=3
        )
    except Exception:
        return []
    names: list[str] = []
    for line in out.splitlines():
        m = re.match(r"\s*\d+\.(\S+)\s+", line)
        if m:
            names.append(m.group(1))
    return names


def _systemd_units_linux() -> list[dict[str, Any]]:
    try:
        out = subprocess.check_output(
            [
                "systemctl",
                "--user",
                "list-units",
                "--type=service",
                "--no-pager",
                "--plain",
                "--no-legend",
                "scitex-agent-container-*",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
    except Exception:
        return []
    units: list[dict[str, Any]] = []
    for line in out.splitlines():
        fields = line.split(None, 4)
        if len(fields) < 4:
            continue
        units.append(
            {
                "unit": fields[0],
                "load": fields[1],
                "active": fields[2],
                "sub": fields[3],
            }
        )
    return units


def _launchd_units_macos() -> list[dict[str, Any]]:
    try:
        out = subprocess.check_output(
            ["launchctl", "list"], text=True, stderr=subprocess.DEVNULL, timeout=3
        )
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for line in out.splitlines()[1:]:
        fields = line.split(None, 2)
        if len(fields) < 3:
            continue
        pid, status, label = fields[0], fields[1], fields[2]
        if (
            "scitex" not in label
            and "orochi" not in label
            and "agent-container" not in label
        ):
            continue
        rows.append(
            {
                "pid": int(pid) if pid.isdigit() else None,
                "status": status,
                "label": label,
            }
        )
    return rows


def _agent_processes() -> list[dict[str, Any]]:
    try:
        out = subprocess.check_output(
            ["ps", "-eo", "pid,etimes,rss,args"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for line in out.splitlines()[1:]:
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        pid, etimes, rss, args = parts
        if "claude" not in args and "scitex-agent-container" not in args:
            continue
        rows.append(
            {
                "pid": int(pid) if pid.isdigit() else None,
                "etime_s": int(etimes) if etimes.isdigit() else None,
                "rss_kb": int(rss) if rss.isdigit() else None,
                "args": args[:300],
            }
        )
    return rows


def collect() -> dict[str, Any]:
    is_macos = platform.system() == "Darwin"
    return {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": _source_host(),
        "os": platform.system(),
        "tmux_sessions": _tmux_sessions(),
        "screen_sessions": _screen_sessions(),
        "service_units": (
            _launchd_units_macos() if is_macos else _systemd_units_linux()
        ),
        "claude_processes": _agent_processes(),
    }


def _ndjson_path(host: str) -> Path:
    root = (
        Path.home() / ".scitex" / "orochi" / "orochi_runtime" / "fleet-watch" / "process-info"
    )
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{host}.ndjson"


def _append_ndjson(payload: dict[str, Any]) -> Path:
    p = _ndjson_path(payload["host"])
    with p.open("a") as f:
        f.write(json.dumps(payload, separators=(",", ":")) + "\n")
    return p


def _one_shot(quiet: bool) -> int:
    payload = collect()
    _append_ndjson(payload)
    if not quiet:
        print(json.dumps(payload, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--loop", type=int, default=0, help="run every N seconds")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    if args.loop <= 0:
        return _one_shot(args.quiet)

    rc = 0
    while True:
        rc = _one_shot(args.quiet)
        time.sleep(args.loop)
    return rc  # unreachable


if __name__ == "__main__":
    sys.exit(main())
