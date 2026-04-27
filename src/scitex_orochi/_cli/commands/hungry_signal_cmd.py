"""``scitex-orochi hungry-signal check`` subcommand.

Python port of ``scripts/client/hungry-signal.sh`` (Layer 2 coordinated
dispatch, msg#16310).

Behaviour summary
-----------------
* Reads this host's canonical ``head-<host>`` agent's ``orochi_subagent_count``
  from either ``scitex-agent-container status --terse --json`` (preferred,
  cheap) or the hub's ``/api/agents/`` endpoint (fallback).
* Tracks consecutive zero-reading cycles in
  ``~/.local/state/scitex/hungry-signal.state``.
* Once ``HUNGRY_THRESHOLD`` (default 2) consecutive zeroes seen AND no DM
  already fired this stretch, posts a DM to ``lead`` via the hub's
  ``/api/messages/`` endpoint. Clears the "fired" flag on the next
  non-zero reading so the next idle stretch re-arms the signal.
* Exits 0 on OK / benign skip. 1 on "already fired this stretch" advisory
  or DM send failure. 2 on parse / hub error. 3 on state-file or yaml
  failure.

Exit-code parity with the shell script is preserved so that existing
cron / launchd consumers keep their severity wiring.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request as _urllib_request
from urllib.error import HTTPError, URLError

import click

from ._host_ops import (
    load_workspace_token,
    parse_head_machines,
    resolve_self_host,
    state_log_dirs,
)

SCHEMA = "scitex-orochi/hungry-signal/v1"
DEFAULT_HUB = "https://scitex-orochi.com"


_LANE_MAP = {
    "mba": "infrastructure",
    "ywata-note-win": "specialized-wsl-access",
    "spartan": "specialized-domain",
    "nas": "hub-admin",
}


def _lane_for(host: str) -> str:
    return _LANE_MAP.get(host, "")


# ---------------------------------------------------------------------------
# orochi_subagent_count readers
# ---------------------------------------------------------------------------

def _read_from_sac(agent: str) -> tuple[int | None, list[str]]:
    """Return (count, alive_agents). count is None on any failure."""
    try:
        proc = subprocess.run(
            ["scitex-agent-container", "status", "--terse", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None, []
    if proc.returncode != 0 or not proc.stdout.strip():
        return None, []
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None, []
    agents: list[dict[str, Any]] = []
    if isinstance(data, list):
        agents = [a for a in data if isinstance(a, dict)]
    elif isinstance(data, dict):
        if isinstance(data.get("agents"), list):
            agents = [a for a in data["agents"] if isinstance(a, dict)]
        else:
            for k, v in data.items():
                if isinstance(v, dict):
                    merged = {**v, "name": v.get("name") or k}
                    agents.append(merged)
    count: int | None = None
    orochi_alive: list[str] = []
    for a in agents:
        name = str(a.get("name") or a.get("agent_id") or "")
        if not name:
            continue
        status = str(a.get("status") or "")
        if status in ("online", "running", "up", "active"):
            orochi_alive.append(name)
        if name == agent:
            c = a.get("orochi_subagent_count")
            try:
                count = int(c) if c is not None else None
            except (TypeError, ValueError):
                count = None
    return count, orochi_alive


def _read_from_hub(agent: str, hub: str, token: str | None) -> tuple[int | None, list[str]]:
    if not token:
        return None, []
    endpoint = hub.rstrip("/") + f"/api/agents/?token={token}"
    req = _urllib_request.Request(
        endpoint,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "scitex-orochi-cli/1.0",
        },
    )
    try:
        with _urllib_request.urlopen(req, timeout=8) as resp:
            if resp.status != 200:
                return None, []
            body = resp.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, OSError):
        return None, []
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None, []
    if not isinstance(data, list):
        return None, []
    count: int | None = None
    orochi_alive: list[str] = []
    for a in data:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name") or "")
        if not name:
            continue
        if str(a.get("status") or "") == "online":
            orochi_alive.append(name)
        if name == agent:
            c = a.get("orochi_subagent_count")
            try:
                count = int(c) if c is not None else None
            except (TypeError, ValueError):
                count = None
    return count, orochi_alive


# ---------------------------------------------------------------------------
# State file
# ---------------------------------------------------------------------------

def _state_get(state_file: Path, host: str) -> tuple[int, int]:
    if not state_file.is_file():
        return 0, 0
    try:
        for line in state_file.read_text().splitlines():
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3 and parts[0] == host:
                try:
                    return int(parts[1] or 0), int(parts[2] or 0)
                except ValueError:
                    return 0, 0
    except OSError:
        return 0, 0
    return 0, 0


def _state_update(
    state_file: Path,
    host: str,
    cycles: int,
    fired: int,
    epoch: int,
) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if state_file.is_file():
        try:
            for line in state_file.read_text().splitlines():
                parts = line.rstrip("\n").split("\t")
                if parts and parts[0] != host:
                    lines.append(line)
        except OSError:
            pass
    lines.append(f"{host}\t{cycles}\t{fired}\t{epoch}")
    state_file.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# DM send
# ---------------------------------------------------------------------------

def _canonical_dm_channel(sender: str, recipient: str) -> str:
    pair = sorted([sender, recipient])
    return f"dm:agent:{pair[0]}|agent:{pair[1]}"


def _send_dm(
    sender: str,
    recipient: str,
    text: str,
    *,
    hub: str,
    token: str,
    timeout: int,
) -> bool:
    channel = _canonical_dm_channel(sender, recipient)
    endpoint = hub.rstrip("/") + f"/api/messages/?token={token}"
    payload = {
        "channel": channel,
        "sender": sender,
        "payload": {"channel": channel, "content": text},
    }
    data = json.dumps(payload).encode("utf-8")
    req = _urllib_request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "scitex-orochi-cli/1.0",
        },
    )
    try:
        with _urllib_request.urlopen(req, timeout=timeout) as resp:
            return resp.status in (200, 201)
    except (HTTPError, URLError, OSError):
        return False


# ---------------------------------------------------------------------------
# Click command
# ---------------------------------------------------------------------------

@click.group("hungry-signal")
def hungry_signal() -> None:
    """Idle-head coordinated-dispatch signalling."""


@hungry_signal.command("check")
@click.option("--dry-run", "dry_run_flag", is_flag=True, help="Explicit dry-run (default).")
@click.option("--yes", "-y", "yes", is_flag=True, help="Actually post the DM and arm state.")
@click.option("--host", "only_host", default=None, help="Override self-host detection.")
@click.option(
    "--threshold",
    type=int,
    default=int(os.environ.get("HUNGRY_THRESHOLD", "2")),
    show_default=True,
    help="Consecutive-zero cycles before a DM fires.",
)
@click.option(
    "--hub",
    envvar="SCITEX_OROCHI_HUB_URL",
    default=DEFAULT_HUB,
    show_default=True,
)
@click.option(
    "--token",
    envvar="SCITEX_OROCHI_TOKEN",
    default=None,
    help="Workspace token [$SCITEX_OROCHI_TOKEN].",
)
@click.option(
    "--curl-timeout",
    type=int,
    default=int(os.environ.get("HUNGRY_CURL_TIMEOUT", "8")),
    show_default=True,
)
def check(
    dry_run_flag: bool,
    yes: bool,
    only_host: str | None,
    threshold: int,
    hub: str,
    token: str | None,
    curl_timeout: int,
) -> None:
    """Run one hungry-signal cycle for this host. Silent no-op when
    ``$SCITEX_HUNGRY_DISABLED=1``.
    """
    del dry_run_flag
    dry_run = not yes

    if os.environ.get("SCITEX_HUNGRY_DISABLED") == "1":
        sys.exit(0)

    state_dir, log_dir = state_log_dirs(
        state_env="HUNGRY_STATE_DIR",
        log_env="HUNGRY_LOG_DIR",
    )
    state_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    state_file = Path(
        os.environ.get("HUNGRY_STATE_FILE")
        or state_dir / "hungry-signal.state"
    )

    # Discover head machines; exit 3 on yaml failure.
    heads = [m.canonical_name for m in parse_head_machines()]
    if not heads:
        click.echo("hungry-signal: no head machines in orochi-machines.yaml", err=True)
        sys.exit(3)

    self_host = only_host or resolve_self_host()
    if self_host not in heads:
        # Non-head host → benign exit 0, like the shell script.
        sys.exit(0)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    agent = f"head-{self_host}"
    lane = _lane_for(self_host)

    resolved_token = token or load_workspace_token()

    # Try sac first, then hub.
    count, orochi_alive = _read_from_sac(agent)
    if count is None:
        count, alive2 = _read_from_hub(agent, hub, resolved_token)
        orochi_alive = orochi_alive or alive2

    def _emit(decision: str, reason: str, *, cc: int, cy: int, fr: int) -> None:
        obj = {
            "schema": SCHEMA,
            "ts": ts,
            "host": self_host,
            "agent": agent,
            "decision": decision,
            "reason": reason,
            "orochi_subagent_count": cc,
            "consecutive_zero_cycles": cy,
            "fired": bool(fr),
            "threshold": threshold,
            "lane": lane,
            "dry_run": dry_run,
        }
        click.echo(json.dumps(obj, separators=(",", ":"), sort_keys=False))

    if count is None:
        _emit("skip", "no_orochi_subagent_count_source", cc=-1, cy=0, fr=0)
        sys.exit(2)

    prior_cycles, prior_fired = _state_get(state_file, self_host)

    if count > 0:
        # Reset state if there's something to reset.
        if (prior_cycles or prior_fired) and not dry_run:
            _state_update(state_file, self_host, 0, 0, now_epoch)
        _emit("noop", f"orochi_subagent_count={count}_reset",
              cc=count, cy=0, fr=0)
        sys.exit(0)

    # count == 0 path.
    new_cycles = prior_cycles + 1

    if new_cycles < threshold:
        if not dry_run:
            _state_update(state_file, self_host, new_cycles, prior_fired, now_epoch)
        _emit("counting",
              f"zero_cycles={new_cycles}/{threshold}",
              cc=count, cy=new_cycles, fr=prior_fired)
        sys.exit(0)

    if prior_fired == 1:
        if not dry_run:
            _state_update(state_file, self_host, new_cycles, 1, now_epoch)
        _emit("skip", "already_fired_awaiting_reset",
              cc=count, cy=new_cycles, fr=1)
        sys.exit(1)

    text = (
        f"{agent}: hungry — 0 orochi_subagents × {new_cycles} cycles, ready for "
        f"dispatch. lane: {lane or 'none'}, orochi_alive: {','.join(orochi_alive) or 'none'}"
    )

    if dry_run:
        _emit("would_dm", "dry_run",
              cc=count, cy=new_cycles, fr=prior_fired)
        sys.exit(0)

    # Non-dry-run, threshold hit: try to send. Failures (including no token
    # / hub down) all collapse to ``dm_failed`` + ``fired=0`` so the next
    # cycle retries, matching shell-script parity.
    ok = False
    if resolved_token:
        ok = _send_dm(
            agent, "lead", text,
            hub=hub, token=resolved_token, timeout=curl_timeout,
        )
    if ok:
        _state_update(state_file, self_host, new_cycles, 1, now_epoch)
        _emit("dm_sent", "hungry_signal_posted",
              cc=count, cy=new_cycles, fr=1)
        sys.exit(0)
    _state_update(state_file, self_host, new_cycles, 0, now_epoch)
    _emit("dm_failed", "send_dm_nonzero",
          cc=count, cy=new_cycles, fr=0)
    sys.exit(1)


__all__ = ["hungry_signal"]
