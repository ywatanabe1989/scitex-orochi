"""Canonical fleet-machine label resolution from shared/config.yaml hostname_aliases.

Resolution chain (first non-empty wins):
  1. hostname_aliases[hostname -s] from shared/config.yaml — canonical
     per-fleet mapping (e.g. ``Yusukes-MacBook-Air`` → ``mba``).
  2. hostname -s (identity fallback) — if the live hostname is not
     aliased, trust the kernel's answer verbatim.
  3. $SCITEX_OROCHI_HOSTNAME / $SCITEX_OROCHI_MACHINE /
     $SCITEX_AGENT_CONTAINER_HOSTNAME (explicit override) — only used
     when the live hostname is unresolvable (empty gethostname() in
     stripped containers). An env override that DISAGREES with a
     populated live hostname is ignored on purpose: that is how a
     stale ``SCITEX_OROCHI_HOSTNAME=mba`` inherited into a spartan
     process silently misreported identity before PR#309 (lead
     msg#15578 — proj-neurovista displayed as mba despite running on
     spartan).

PR#309 flipped the priority so hostname() beats env vars — which was
the right fix, but it was incomplete: the TS heartbeat skipped the
``hostname_aliases`` map entirely, so raw OS hostnames like
``Yusukes-MacBook-Air`` started showing up on the dashboard instead
of the canonical ``mba`` (ywatanabe msg#16102). This module + the
TS ``resolveHostLabel`` share the same resolution order so the hub
always sees a consistent "mba" / "nas" / "spartan" /
"ywata-note-win" regardless of raw OS hostname or launch env.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path


def _load_hostname_aliases() -> dict[str, str]:
    """Return ``spec.hostname_aliases`` from shared/config.yaml, or ``{}``.

    Never raises — host identity resolution MUST still succeed via the
    raw-hostname fallback even if the config file is missing, malformed,
    or PyYAML is unavailable.
    """
    try:
        import yaml as _yaml  # PyYAML ships with the fleet.
    except ImportError:
        return {}
    try:
        cfg_path = Path.home() / ".scitex" / "orochi" / "shared" / "config.yaml"
        if not cfg_path.exists():
            return {}
        _cfg = _yaml.safe_load(cfg_path.read_text()) or {}
    except Exception:
        return {}
    _aliases = (_cfg.get("spec") or {}).get("hostname_aliases") or {}
    if not isinstance(_aliases, dict):
        return {}
    return {str(k): str(v) for k, v in _aliases.items()}


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
    3. ``$SCITEX_OROCHI_HOSTNAME`` / ``$SCITEX_OROCHI_MACHINE`` /
       ``$SCITEX_AGENT_CONTAINER_HOSTNAME`` — explicit override, only
       honoured when steps 1/2 produced an empty string (broken
       container, ``gethostname()`` returning ""). An env override
       that DISAGREES with the live hostname is ignored on purpose —
       that's how ``mba`` env leaked into a spartan process before
       PR#309.
    """
    raw_host = (socket.gethostname() or "").split(".")[0].strip()
    if raw_host:
        _aliases = _load_hostname_aliases()
        if raw_host in _aliases:
            return _aliases[raw_host]
        return raw_host
    # gethostname() returned empty — only now trust the env override.
    return (
        os.environ.get("SCITEX_OROCHI_HOSTNAME", "").strip()
        or os.environ.get("SCITEX_OROCHI_MACHINE", "").strip()
        or os.environ.get("SCITEX_AGENT_CONTAINER_HOSTNAME", "").strip()
    )


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
