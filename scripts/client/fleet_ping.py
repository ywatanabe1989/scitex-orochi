#!/usr/bin/env python3
"""
fleet_ping.py — bi-directional fleet ping/pong daemon.

Pings all known fleet hosts via SSH (lightweight 'echo pong') and records RTT
to ~/.scitex/orochi/runtime/fleet-watch/ping/<source-host>.ndjson. Each line records
one ping round for all targets from this host, so downstream cross-correlation
can detect partition asymmetry (A reaches B but B can't reach A).

Host identity:
    SOURCE = ${SCITEX_OROCHI_HOSTNAME:-$(hostname -s)}

Target list (ywata-note-win, mba, nas, spartan) overridable via --targets or
$SCITEX_OROCHI_FLEET_HOSTS. Self-ping is always skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_TARGETS = ["ywata-note-win", "mba", "nas", "spartan"]


def _source_host() -> str:
    h = os.environ.get("SCITEX_OROCHI_HOSTNAME") or ""
    if h:
        return h
    return socket.gethostname().split(".", 1)[0]


def _ssh_ping(target: str, timeout: float) -> dict[str, Any]:
    """One lightweight 'echo pong' round-trip over SSH."""
    t0 = time.perf_counter()
    try:
        out = subprocess.run(
            [
                "ssh",
                "-o",
                f"ConnectTimeout={int(timeout)}",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                target,
                "echo pong",
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 2,
        )
        dt_ms = int((time.perf_counter() - t0) * 1000)
        ok = out.returncode == 0 and out.stdout.strip() == "pong"
        return {
            "target": target,
            "ok": ok,
            "rtt_ms": dt_ms if ok else None,
            "exit_code": out.returncode,
            "stderr": (out.stderr or "").strip()[-200:],
        }
    except subprocess.TimeoutExpired:
        return {
            "target": target,
            "ok": False,
            "rtt_ms": None,
            "exit_code": -1,
            "stderr": "timeout",
        }
    except Exception as e:
        return {
            "target": target,
            "ok": False,
            "rtt_ms": None,
            "exit_code": -1,
            "stderr": f"{type(e).__name__}: {e}"[:200],
        }


def collect(targets: list[str], timeout: float) -> dict[str, Any]:
    source = _source_host()
    rounds = [_ssh_ping(t, timeout) for t in targets if t != source]
    reachable = sum(1 for r in rounds if r["ok"])
    return {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": source,
        "reachable": reachable,
        "total_targets": len(rounds),
        "rounds": rounds,
    }


def _ndjson_path(host: str) -> Path:
    root = Path.home() / ".scitex" / "orochi" / "runtime" / "fleet-watch" / "ping"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{host}.ndjson"


def _append_ndjson(payload: dict[str, Any]) -> Path:
    p = _ndjson_path(payload["source"])
    with p.open("a") as f:
        f.write(json.dumps(payload, separators=(",", ":")) + "\n")
    return p


def _parse_targets(val: str | None) -> list[str]:
    if val:
        return [t.strip() for t in val.split(",") if t.strip()]
    env = os.environ.get("SCITEX_OROCHI_FLEET_HOSTS", "")
    if env:
        return [t.strip() for t in env.split(",") if t.strip()]
    return list(DEFAULT_TARGETS)


def _one_shot(targets: list[str], timeout: float, quiet: bool) -> int:
    payload = collect(targets, timeout)
    _append_ndjson(payload)
    if not quiet:
        print(json.dumps(payload, indent=2))
    return 0 if payload["reachable"] == payload["total_targets"] else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--targets", default=None, help="comma-separated host list")
    p.add_argument("--timeout", type=float, default=6.0, help="SSH connect timeout sec")
    p.add_argument("--loop", type=int, default=0, help="run every N seconds")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    targets = _parse_targets(args.targets)
    if args.loop <= 0:
        return _one_shot(targets, args.timeout, args.quiet)

    rc = 0
    while True:
        rc = _one_shot(targets, args.timeout, args.quiet)
        time.sleep(args.loop)
    return rc  # unreachable


if __name__ == "__main__":
    sys.exit(main())
