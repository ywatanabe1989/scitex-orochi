"""Canonical fleet-machine label resolution from shared/config.yaml hostname_aliases.

Resolution chain (first wins):
  1. $SCITEX_OROCHI_HOSTNAME
  2. hostname_aliases[hostname -s] from shared/config.yaml
  3. hostname -s (identity fallback)

This matches config._host.resolve_hostname() on the sac side and the
shared/scripts/resolve-hostname helper used by bootstrap + shell
scripts, so the hub always sees a consistent "mba" / "nas" / "spartan"
/ "ywata-note-win" regardless of raw OS hostname.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path


def resolve_machine_label() -> str:
    machine = os.environ.get("SCITEX_OROCHI_HOSTNAME", "").strip()
    if machine:
        return machine
    raw_host = socket.gethostname().split(".")[0]
    try:
        import yaml as _yaml  # PyYAML ships with the fleet.

        cfg_path = Path.home() / ".scitex" / "orochi" / "shared" / "config.yaml"
        if cfg_path.exists():
            _cfg = _yaml.safe_load(cfg_path.read_text()) or {}
            _aliases = (_cfg.get("spec") or {}).get("hostname_aliases") or {}
            if isinstance(_aliases, dict) and raw_host in _aliases:
                return str(_aliases[raw_host])
    except Exception:
        pass
    return raw_host


def find_session_pids(agent: str, multiplexer: str) -> tuple[int, int]:
    """Return (pid, ppid) for the agent's tmux pane and its claude descendant."""
    import subprocess

    pid = 0
    ppid = 0
    try:
        if multiplexer == "tmux":
            out = (
                subprocess.run(
                    ["tmux", "list-panes", "-t", agent, "-F", "#{pane_pid}"],
                    capture_output=True,
                    text=True,
                )
                .stdout.strip()
                .splitlines()
            )
            if out:
                ppid = int(out[0])
                ps = (
                    subprocess.run(
                        ["pgrep", "-P", str(ppid), "-f", "claude"],
                        capture_output=True,
                        text=True,
                    )
                    .stdout.strip()
                    .splitlines()
                )
                if ps:
                    pid = int(ps[0])
                else:
                    pid = ppid
    except Exception:
        pass
    return pid, ppid
