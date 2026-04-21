"""Canonical fleet-machine label resolution from shared/config.yaml hostname_aliases.

Resolution chain (first wins):
  1. hostname_aliases[hostname -s] from shared/config.yaml
  2. hostname -s (identity fallback)
  3. $SCITEX_OROCHI_HOSTNAME (explicit override, only used when the live
     hostname is unresolvable — e.g. empty gethostname() in stripped
     containers). Previously this env var was primary, which made
     env-pollution (a shared tmux / systemd env with a stale
     ``SCITEX_OROCHI_HOSTNAME=mba`` inherited into a spartan process)
     silently misreport the host identity (lead msg#15578 — proj-
     neurovista displayed as mba despite running on spartan). Per
     lead's root fix: the agent's ``host`` field in the heartbeat
     comes from its own ``hostname()`` call, never from inherited
     env or server-side inference.

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
    """Return the canonical fleet-machine label for THIS host.

    Trust order (highest trust first):

    1. ``hostname_aliases[gethostname().split('.')[0]]`` from
       ``~/.scitex/orochi/shared/config.yaml`` — canonical per-fleet
       mapping (e.g. ``Yusukes-MacBook-Air`` → ``mba``).
    2. Raw ``socket.gethostname().split('.')[0]`` — if the live hostname
       is not aliased in config, fall through to it directly. This is
       the proof-of-life identity: whatever the kernel says this
       process is running on.
    3. ``$SCITEX_OROCHI_HOSTNAME`` — explicit override, only honoured
       when steps 1/2 produced an empty string (broken container,
       ``gethostname()`` returning ""). An env override that DISAGREES
       with the live hostname is ignored on purpose — that's how
       ``mba`` env leaked into a spartan process before this fix.
    """
    raw_host = (socket.gethostname() or "").split(".")[0].strip()
    if raw_host:
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
    # gethostname() returned empty — only now trust the env override.
    return os.environ.get("SCITEX_OROCHI_HOSTNAME", "").strip()


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
