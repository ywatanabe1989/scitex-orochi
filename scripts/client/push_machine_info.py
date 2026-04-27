#!/usr/bin/env python3
"""
push_machine_info.py — per-host orochi_machine info pusher for the Orochi fleet.

One-shot: collects OS / arch / CPU / memory / disk / uptime / load for the
running host, appends an NDJSON line to ~/.scitex/orochi/runtime/fleet-watch/
orochi_machine-info/<host>.ndjson, and optionally POSTs to the hub.

Idempotent. Designed to be run from cron / systemd timer every N minutes,
or as `--loop 300` for a long-running daemon-style process.

Host identity follows the fleet convention:
    HOST = ${SCITEX_OROCHI_HOSTNAME:-$(orochi_hostname -s)}

Hub endpoint: override via --url or $SCITEX_OROCHI_HUB_URL. If neither is
set, the script only writes NDJSON — safe no-op for initial rollout.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _canonical_host() -> str:
    h = os.environ.get("SCITEX_OROCHI_HOSTNAME") or ""
    if h:
        return h
    return socket.gethostname().split(".", 1)[0]


def _cpu_count() -> int:
    try:
        return os.cpu_count() or 0
    except Exception:
        return 0


def _mem_mb() -> int | None:
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        try:
            for line in meminfo.read_text().splitlines():
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return kb // 1024
        except Exception:
            return None
    # macOS fallback
    try:
        out = subprocess.check_output(
            ["sysctl", "-n", "hw.memsize"], text=True, timeout=2
        ).strip()
        return int(out) // (1024 * 1024)
    except Exception:
        return None


def _load_avg() -> tuple[float, float, float] | None:
    try:
        return os.getloadavg()
    except Exception:
        return None


def _disk_free_pct(path: str = str(Path.home())) -> int | None:
    try:
        total, _used, free = shutil.disk_usage(path)
        if total == 0:
            return None
        return int(round(free / total * 100))
    except Exception:
        return None


def _uptime_s() -> float | None:
    try:
        return float(Path("/proc/uptime").read_text().split()[0])
    except Exception:
        pass
    try:
        out = subprocess.check_output(
            ["sysctl", "-n", "kern.boottime"], text=True, timeout=2
        ).strip()
        # { sec = 1234567890, usec = ... } Thu ...
        sec_part = out.split("sec = ")[1].split(",")[0]
        return time.time() - int(sec_part)
    except Exception:
        return None


def collect() -> dict[str, Any]:
    la = _load_avg()
    return {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": _canonical_host(),
        "os": platform.system(),
        "os_release": platform.release(),
        "arch": platform.orochi_machine(),
        "python": platform.python_version(),
        "cpu_count": _cpu_count(),
        "mem_mb": _mem_mb(),
        "disk_free_pct_home": _disk_free_pct(),
        "load_1min": la[0] if la else None,
        "load_5min": la[1] if la else None,
        "load_15min": la[2] if la else None,
        "uptime_s": _uptime_s(),
    }


def _ndjson_path(host: str) -> Path:
    root = (
        Path.home() / ".scitex" / "orochi" / "runtime" / "fleet-watch" / "orochi_machine-info"
    )
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{host}.ndjson"


def _append_ndjson(payload: dict[str, Any]) -> Path:
    p = _ndjson_path(payload["host"])
    with p.open("a") as f:
        f.write(json.dumps(payload, separators=(",", ":")) + "\n")
    return p


def _post_hub(url: str, payload: dict[str, Any], timeout: float) -> int:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode()
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def _one_shot(url: str | None, timeout: float, quiet: bool) -> int:
    payload = collect()
    ndjson = _append_ndjson(payload)
    code = 0
    if url:
        code = _post_hub(url, payload, timeout)
    if not quiet:
        print(json.dumps({"ndjson": str(ndjson), "post_code": code, **payload}))
    return 0 if (not url or 200 <= code < 300) else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default=os.environ.get("SCITEX_OROCHI_HUB_URL", ""))
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("--loop", type=int, default=0, help="run every N seconds")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    url = args.url or None
    if args.loop <= 0:
        return _one_shot(url, args.timeout, args.quiet)

    rc = 0
    while True:
        rc = _one_shot(url, args.timeout, args.quiet)
        time.sleep(args.loop)
    return rc  # unreachable


if __name__ == "__main__":
    sys.exit(main())
