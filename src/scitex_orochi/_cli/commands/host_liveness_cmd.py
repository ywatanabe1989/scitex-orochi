"""``scitex-orochi host-liveness probe`` subcommand.

Python port of ``scripts/client/fleet-watch/host-liveness-probe.sh``.
Enumerates every orochi_machine in ``orochi-machines.yaml``, SSH-probes it
(or short-circuits to local ``bash``), and emits one NDJSON line per
host on stdout. With ``--yes`` it revives missing expected tmux
sessions via the local healer's inbox or a direct ``ssh
scitex-agent-container start`` invocation.

Flag parity with the shell original:

==============  ============================================================
Flag            Meaning
==============  ============================================================
--dry-run       default — log "would revive" actions without side effects.
--yes / -y      actually revive missing agents.
--host NAME     constrain to one orochi_machine.
==============  ============================================================
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from ._host_ops import (
    MachineEntry,
    default_machines_yaml,
    parse_all_machines,
)

SCHEMA = "scitex-orochi/host-liveness-probe/v1"

_PROBE_SCRIPT = """
PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
if command -v tmux >/dev/null 2>&1; then
  if tmux_out=$(tmux list-sessions -F "#{session_name}" 2>/dev/null); then
    echo "TMUX_OK"
    echo "$tmux_out"
  else
    echo "TMUX_DEAD"
  fi
else
  echo "TMUX_MISSING"
fi
""".strip()


@dataclass
class HostProbeResult:
    host: str
    severity: str
    reachable: bool
    tmux_state: str
    expected_agents: list[str]
    alive_agents: list[str]
    missing: list[str]
    unexpected: list[str]
    revive_path: str
    actions_taken: list[str]

    def as_dict(self, ts: str) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "ts": ts,
            "host": self.host,
            "severity": self.severity,
            "reachable": self.reachable,
            "tmux_state": self.tmux_state,
            "expected_agents": self.expected_agents,
            "alive_agents": self.alive_agents,
            "missing": self.missing,
            "unexpected": self.unexpected,
            "revive_path": self.revive_path,
            "actions_taken": self.actions_taken,
        }


# ---------------------------------------------------------------------------
# Local-vs-remote detection
# ---------------------------------------------------------------------------

def _is_local(host: str, aliases: tuple[str, ...]) -> bool:
    local_env = os.environ.get("SCITEX_AGENT_LOCAL_HOSTS", "")
    hosts_from_env = {h for h in local_env.split(",") if h}
    local_host_short = socket.gethostname().split(".")[0]
    local_fqdn = socket.gethostname()
    if host in hosts_from_env:
        return True
    if host == local_host_short or host == local_fqdn:
        return True
    for a in aliases:
        if a in hosts_from_env:
            return True
        if a == local_host_short or a == local_fqdn:
            return True
    return False


# ---------------------------------------------------------------------------
# SSH probe
# ---------------------------------------------------------------------------

def _timeout_prefix(seconds: int) -> list[str]:
    if shutil.which("timeout"):
        return ["timeout", str(seconds)]
    if shutil.which("gtimeout"):
        return ["gtimeout", str(seconds)]
    return []


def _probe_host_raw(
    host: str,
    *,
    is_local: bool,
    connect_timeout: int,
    probe_timeout: int,
) -> tuple[str, int]:
    """Run the probe script on host, return (stdout, returncode)."""
    if is_local:
        proc = subprocess.run(
            ["bash", "-c", _PROBE_SCRIPT],
            capture_output=True,
            text=True,
            timeout=probe_timeout,
        )
        return proc.stdout, proc.returncode
    ssh_args = [
        "ssh",
        "-o", f"ConnectTimeout={connect_timeout}",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ServerAliveInterval=3",
        "-o", "ServerAliveCountMax=2",
        host,
        "bash -s",
    ]
    cmd = _timeout_prefix(probe_timeout) + ssh_args
    try:
        proc = subprocess.run(
            cmd,
            input=_PROBE_SCRIPT,
            capture_output=True,
            text=True,
            timeout=probe_timeout + 2,
        )
        return proc.stdout, proc.returncode
    except subprocess.TimeoutExpired:
        return "", 124


def _classify(
    stdout: str,
    rc: int,
    expected: tuple[str, ...],
) -> tuple[str, int, bool, str, list[str], list[str], list[str]]:
    """Return
    (severity, severity_code, reachable, tmux_state, alive, missing, unexpected).
    """
    if rc != 0 or not stdout.strip():
        return "critical", 3, False, "ssh_unreachable", [], list(expected), []
    lines = stdout.splitlines()
    first = lines[0].strip() if lines else ""
    alive: list[str] = []
    if first == "TMUX_OK":
        tmux_state = "running"
        alive = [ln.strip() for ln in lines[1:] if ln.strip()]
    elif first == "TMUX_DEAD":
        return "critical", 3, True, "dead", [], list(expected), []
    elif first == "TMUX_MISSING":
        return "critical", 3, True, "tmux_not_installed", [], list(expected), []
    else:
        return "critical", 3, False, "unparseable", [], list(expected), []

    alive_set = set(alive)
    expected_set = set(expected)
    missing = [e for e in expected if e not in alive_set]
    unexpected = [a for a in alive if a not in expected_set] if expected else []

    severity, code = "ok", 0
    if missing:
        severity, code = "warn", 2
    elif unexpected:
        severity, code = "advisory", 1
    return severity, code, True, tmux_state, alive, missing, unexpected


# ---------------------------------------------------------------------------
# Revive paths
# ---------------------------------------------------------------------------

def _revive_agent(
    host: str,
    agent: str,
    path: str,
    *,
    is_local: bool,
    connect_timeout: int,
    probe_timeout: int,
) -> bool:
    """Return True on success, False otherwise."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if path == "healer_delegate":
        local_host = socket.gethostname().split(".")[0]
        inbox_dir = f"$HOME/.scitex/orochi/healer-{host}"
        line = f"revive {agent} at {ts} by host-liveness-probe@{local_host}"
        cmd = (
            f"if [ -d {inbox_dir} ]; then "
            f"printf '%s\\n' '{line}' >> {inbox_dir}/inbox; echo INBOX_OK; "
            f"else echo NO_INBOX; fi"
        )
        if is_local:
            proc = subprocess.run(
                ["bash", "-lc", cmd],
                capture_output=True,
                text=True,
                timeout=probe_timeout,
            )
            out = proc.stdout + proc.stderr
        else:
            full = _timeout_prefix(probe_timeout) + [
                "ssh",
                "-o", f"ConnectTimeout={connect_timeout}",
                "-o", "BatchMode=yes",
                "-o", "ServerAliveInterval=3",
                "-o", "ServerAliveCountMax=2",
                host, cmd,
            ]
            try:
                proc = subprocess.run(
                    full, capture_output=True, text=True,
                    timeout=probe_timeout + 2,
                )
                out = proc.stdout + proc.stderr
            except subprocess.TimeoutExpired:
                out = ""
        if "INBOX_OK" in out:
            return True
        # fall through to ssh_direct

    # ssh_direct
    start_cmd = (
        f"scitex-agent-container start {agent} 2>&1 || "
        f"sac start {agent} 2>&1"
    )
    if is_local:
        proc = subprocess.run(
            ["bash", "-lc", start_cmd],
            capture_output=True,
            text=True,
            timeout=probe_timeout * 4,
        )
        return proc.returncode == 0
    full = _timeout_prefix(probe_timeout * 4) + [
        "ssh",
        "-o", f"ConnectTimeout={connect_timeout}",
        "-o", "BatchMode=yes",
        "-o", "ServerAliveInterval=3",
        "-o", "ServerAliveCountMax=2",
        host, start_cmd,
    ]
    try:
        proc = subprocess.run(
            full,
            capture_output=True, text=True,
            timeout=probe_timeout * 4 + 2,
        )
        return proc.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def _probe_machine(
    m: MachineEntry,
    *,
    dry_run: bool,
    connect_timeout: int,
    probe_timeout: int,
) -> HostProbeResult:
    is_local = _is_local(m.canonical_name, m.aliases)
    stdout, rc = _probe_host_raw(
        m.canonical_name,
        is_local=is_local,
        connect_timeout=connect_timeout,
        probe_timeout=probe_timeout,
    )
    severity, _code, reachable, tmux_state, alive, missing, unexpected = _classify(
        stdout, rc, m.expected_tmux_sessions
    )

    revive_path = "none"
    actions: list[str] = []
    if tmux_state == "running" and missing:
        healer = f"healer-{m.canonical_name}"
        mamba_healer = f"mamba-healer-{m.canonical_name}"
        healer_alive = healer in alive or mamba_healer in alive
        revive_path = "healer_delegate" if healer_alive else "ssh_direct"
        for miss in missing:
            if dry_run:
                actions.append(f"would_revive:{miss}:via={revive_path}")
            else:
                ok = _revive_agent(
                    m.canonical_name, miss, revive_path,
                    is_local=is_local,
                    connect_timeout=connect_timeout,
                    probe_timeout=probe_timeout,
                )
                tag = "revived" if ok else "revive_failed"
                actions.append(f"{tag}:{miss}:via={revive_path}")
    return HostProbeResult(
        host=m.canonical_name,
        severity=severity,
        reachable=reachable,
        tmux_state=tmux_state,
        expected_agents=list(m.expected_tmux_sessions),
        alive_agents=alive,
        missing=missing,
        unexpected=unexpected,
        revive_path=revive_path,
        actions_taken=actions,
    )


# ---------------------------------------------------------------------------
# Click entry point
# ---------------------------------------------------------------------------

_SEVERITY_CODE = {"ok": 0, "advisory": 1, "warn": 2, "critical": 3}


@click.group("host-liveness")
def host_liveness() -> None:
    """Fleet host liveness probe."""


@host_liveness.command("probe")
@click.option("--dry-run", "dry_run_flag", is_flag=True, help="Explicit dry-run (default).")
@click.option("--yes", "-y", "yes", is_flag=True, help="Actually revive missing agents.")
@click.option("--host", "only_host", default=None, help="Constrain to one host.")
@click.option(
    "--machines-yaml",
    type=click.Path(path_type=Path),
    default=None,
    help="Override orochi-machines.yaml path.",
)
@click.option(
    "--ssh-connect-timeout",
    type=int,
    default=int(os.environ.get("SSH_CONNECT_TIMEOUT", "5")),
    show_default=True,
)
@click.option(
    "--ssh-timeout",
    type=int,
    default=int(os.environ.get("SSH_TIMEOUT", "8")),
    show_default=True,
)
def probe(
    dry_run_flag: bool,
    yes: bool,
    only_host: str | None,
    machines_yaml: Path | None,
    ssh_connect_timeout: int,
    ssh_timeout: int,
) -> None:
    """Probe every fleet host; emit one NDJSON line per host on stdout.

    Exits with the *worst* severity observed:
    ``0`` ok, ``1`` advisory, ``2`` warn, ``3`` critical.
    """
    dry_run = not yes  # --yes overrides --dry-run
    del dry_run_flag  # we just need yes to flip the mode
    path = machines_yaml or default_machines_yaml()
    machines = parse_all_machines(path)
    if not machines:
        click.echo(
            f"host-liveness-probe: no machines in {path}",
            err=True,
        )
        sys.exit(3)

    if only_host:
        machines = [m for m in machines if m.canonical_name == only_host]
        if not machines:
            click.echo(
                f"host-liveness-probe: host '{only_host}' not in {path}",
                err=True,
            )
            sys.exit(3)

    worst = 0
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for m in machines:
        result = _probe_machine(
            m,
            dry_run=dry_run,
            connect_timeout=ssh_connect_timeout,
            probe_timeout=ssh_timeout,
        )
        click.echo(
            json.dumps(result.as_dict(ts), separators=(",", ":"), sort_keys=False)
        )
        worst = max(worst, _SEVERITY_CODE.get(result.severity, 0))
        if result.severity != "ok":
            click.echo(
                f"host-liveness-probe {result.severity} on {result.host}: "
                f"tmux={result.tmux_state} missing={result.missing} "
                f"unexpected={result.unexpected} "
                f"actions={result.actions_taken}",
                err=True,
            )
    sys.exit(worst)


# Platform-aware log path advertised to launchd / systemd templates.
def _default_log_dir() -> Path:
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Logs" / "scitex"
    return Path.home() / ".scitex" / "orochi" / "fleet-watch"


__all__ = ["host_liveness"]
