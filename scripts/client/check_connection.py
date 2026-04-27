#!/usr/bin/env python3
"""
check_connection.py — hub WebSocket / HTTPS connection health checker.

Periodically probes wss://scitex-orochi.com (and its HTTPS twin) from this
host, measures latency, records to ~/.scitex/orochi/orochi_runtime/fleet-watch/
connection/<host>.ndjson. Lets the fleet detect when a given host has DNS / TLS /
tunnel problems independent of agent health.

Defaults to the canonical hub but overridable via --url or
$SCITEX_OROCHI_HUB_URL.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_WSS = "wss://scitex-orochi.com"
DEFAULT_HTTPS = "https://scitex-orochi.com/healthz"


def _source_host() -> str:
    h = os.environ.get("SCITEX_OROCHI_HOSTNAME") or ""
    if h:
        return h
    return socket.gethostname().split(".", 1)[0]


def _probe_https(url: str, timeout: float) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, method="GET")
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            dt = int((time.perf_counter() - t0) * 1000)
            return {
                "url": url,
                "ok": 200 <= resp.getcode() < 400,
                "status": resp.getcode(),
                "latency_ms": dt,
                "err": None,
            }
    except urllib.error.HTTPError as e:
        dt = int((time.perf_counter() - t0) * 1000)
        # 404 on /healthz is still a "reachable server" signal
        return {
            "url": url,
            "ok": e.code < 500,
            "status": e.code,
            "latency_ms": dt,
            "err": None,
        }
    except Exception as e:
        dt = int((time.perf_counter() - t0) * 1000)
        return {
            "url": url,
            "ok": False,
            "status": None,
            "latency_ms": dt,
            "err": f"{type(e).__name__}: {e}"[:200],
        }


def _probe_tls(wss_url: str, timeout: float) -> dict[str, Any]:
    """TLS-level reachability for the WS endpoint (no actual WS handshake)."""
    parsed = urlparse(wss_url)
    host = parsed.orochi_hostname or ""
    port = parsed.port or (443 if parsed.scheme in ("wss", "https") else 80)
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            if parsed.scheme in ("wss", "https"):
                ctx = ssl.create_default_context()
                with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                    peer_cert = ssock.getpeercert()
                    dt = int((time.perf_counter() - t0) * 1000)
                    return {
                        "url": wss_url,
                        "ok": True,
                        "latency_ms": dt,
                        "tls_subject": peer_cert.get("subject") if peer_cert else None,
                        "err": None,
                    }
            dt = int((time.perf_counter() - t0) * 1000)
            return {
                "url": wss_url,
                "ok": True,
                "latency_ms": dt,
                "tls_subject": None,
                "err": None,
            }
    except Exception as e:
        dt = int((time.perf_counter() - t0) * 1000)
        return {
            "url": wss_url,
            "ok": False,
            "latency_ms": dt,
            "tls_subject": None,
            "err": f"{type(e).__name__}: {e}"[:200],
        }


def collect(https_url: str, wss_url: str, timeout: float) -> dict[str, Any]:
    return {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": _source_host(),
        "https": _probe_https(https_url, timeout),
        "wss_tls": _probe_tls(wss_url, timeout),
    }


def _ndjson_path(host: str) -> Path:
    root = Path.home() / ".scitex" / "orochi" / "orochi_runtime" / "fleet-watch" / "connection"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{host}.ndjson"


def _append_ndjson(payload: dict[str, Any]) -> Path:
    p = _ndjson_path(payload["host"])
    with p.open("a") as f:
        f.write(json.dumps(payload, separators=(",", ":")) + "\n")
    return p


def _one_shot(https_url: str, wss_url: str, timeout: float, quiet: bool) -> int:
    payload = collect(https_url, wss_url, timeout)
    _append_ndjson(payload)
    if not quiet:
        print(json.dumps(payload, indent=2))
    ok = payload["https"]["ok"] and payload["wss_tls"]["ok"]
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--https-url", default=DEFAULT_HTTPS)
    p.add_argument(
        "--wss-url",
        default=os.environ.get("SCITEX_OROCHI_HUB_URL", DEFAULT_WSS),
    )
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("--loop", type=int, default=0)
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    if args.loop <= 0:
        return _one_shot(args.https_url, args.wss_url, args.timeout, args.quiet)

    rc = 0
    while True:
        rc = _one_shot(args.https_url, args.wss_url, args.timeout, args.quiet)
        time.sleep(args.loop)
    return rc  # unreachable


if __name__ == "__main__":
    sys.exit(main())
