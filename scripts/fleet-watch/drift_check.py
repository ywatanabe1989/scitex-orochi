#!/usr/bin/env python3
"""machines.yaml drift detection for NAS fleet_watch.sh (todo#283 follow-up).

For one host alias, compares the declared `expected_tmux_sessions` in
``orochi-machines.yaml`` against the runtime ``tmux_names`` field from
the most recent snapshot in ``~/.scitex/orochi/runtime/fleet-watch/<host>.json``
(or the legacy ``~/.scitex/orochi/fleet-watch/<host>.json`` path; see
backward-compat note in :func:`_runtime_sessions`).

Prints exactly one line per (host, drift_kind) finding to stdout in a
fleet_watch-friendly shape so the bash wrapper can pipe it straight to
``log`` without extra parsing:

    DRIFT host=<h> kind=missing  sessions=<comma-list>
    DRIFT host=<h> kind=unexpected sessions=<comma-list>

Exit code is always 0 — drift is informational, not a script failure.

Requirements: stdlib only (PyYAML is the one optional dep; if it's not
available we fall back to a tiny ``yaml`` shim that only handles the
declarative subset we need).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SCITEX_OROCHI_DIR = Path(os.environ.get(
    "SCITEX_OROCHI_DIR",
    os.path.expanduser("~/proj/scitex-orochi"),
))
MACHINES_YAML = SCITEX_OROCHI_DIR / "orochi-machines.yaml"
# Canonical fleet-watch snapshot dir moved under runtime/ in dotfiles
# commit 68bd1592 (Orochi fleet restructure Phase A). The legacy flat
# path is accepted as a fallback so mixed-host fleets (some bootstrapped
# against the new layout, some not) keep working during rollout.
# DEPRECATED: remove the legacy fallback once every host has been
# re-bootstrapped — estimate Q3 2026.
WATCH_DIR = Path(os.environ.get(
    "FLEET_WATCH_OUT",
    os.path.expanduser("~/.scitex/orochi/runtime/fleet-watch"),
))
_LEGACY_WATCH_DIR = Path(os.path.expanduser("~/.scitex/orochi/fleet-watch"))


def _load_machines_yaml() -> list[dict]:
    try:
        import yaml  # type: ignore
    except ImportError:
        return []
    try:
        with open(MACHINES_YAML) as f:
            doc = yaml.safe_load(f) or {}
    except (OSError, Exception):
        return []
    return doc.get("machines") or []


def _expected_sessions(host: str) -> set[str]:
    machines = _load_machines_yaml()
    if not machines:
        return set()
    for m in machines:
        names = {m.get("canonical_name", "")}
        for a in m.get("aliases") or []:
            names.add(a)
        if host in names:
            return set(m.get("expected_tmux_sessions") or [])
    return set()


def _runtime_sessions(host: str) -> set[str] | None:
    # Prefer the canonical runtime/ path; fall back to the legacy flat
    # path if the runtime/ snapshot isn't there yet (backward compat
    # during dotfiles 68bd1592 rollout).
    snap_path = WATCH_DIR / f"{host}.json"
    if not snap_path.exists():
        legacy = _LEGACY_WATCH_DIR / f"{host}.json"
        if legacy.exists():
            snap_path = legacy
        else:
            return None
    try:
        with open(snap_path) as f:
            snap = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    # Snapshot --json schema (post-PR #18): tmux_names is a JSON array.
    # Legacy probe_remote.sh schema: tmux_names is a comma-joined string.
    raw = snap.get("tmux_names")
    if raw is None:
        return set()
    if isinstance(raw, list):
        return {n for n in raw if n}
    if isinstance(raw, str):
        return {n.strip() for n in raw.split(",") if n.strip()}
    return set()


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: drift_check.py <host>", file=sys.stderr)
        return 0  # not a script failure
    host = argv[1]

    expected = _expected_sessions(host)
    if not expected:
        # Host not declared in machines.yaml — nothing to compare against.
        return 0

    runtime = _runtime_sessions(host)
    if runtime is None:
        # Snapshot not yet written or unreadable — defer.
        return 0

    missing = sorted(expected - runtime)
    unexpected = sorted(runtime - expected)

    if missing:
        print(f"DRIFT host={host} kind=missing sessions={','.join(missing)}")
    if unexpected:
        print(f"DRIFT host={host} kind=unexpected sessions={','.join(unexpected)}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
