#!/usr/bin/env python3
"""fleet_sub_snapshot — fleet launch-time subscription snapshot (todo#451/#453).

Walks every host's `~/.scitex/orochi/workspaces/*/` directory (via find,
not bash-glob, for portability across Linux + macOS), reads the runtime
`.mcp.json` for each agent, and emits one NDJSON record per (host, agent)
pair describing the **launch-time seed** channel subscription list plus
a drift comparison against the canonical dotfiles `src_mcp.json`.

IMPORTANT — what this probe IS and is NOT:

- IS: a snapshot of the `SCITEX_OROCHI_CHANNELS` env var that was written
  to the workspace `.mcp.json` at agent launch time. Useful for catching
  first-connect subscription drift — when a newly-launched agent's bridge
  starts with a channel list that doesn't match canonical dotfiles.

- IS NOT: a source of truth for live subscription state. Per head-mba's
  msg#12749 verification (todo#453 investigation), the hub-side
  ``ChannelMembership`` registry is authoritative — long-running agents
  subscribe to channels added post-launch (e.g. ``#heads``, created after
  head-mba was launched) without any .mcp.json update. A stale runtime
  .mcp.json therefore does not imply the live bridge has stale
  subscriptions; it only tells you what the launch-time seed was.

Drift classification:

- ``aligned``     — runtime matches canonical. Healthy.
- ``drift``       — runtime differs from canonical. CANDIDATE only, not
                    confirmed orphan. Requires cross-referencing with
                    actual hub traffic (an MCP-session tool, not this
                    script) to confirm whether the live bridge is missing
                    any channels it should have.
- ``no_canonical``— workspace exists but no dotfiles src_mcp.json — likely
                    legacy workspace from an agent that no longer exists
                    as a canonical identity. Informational only.

Output file: ``~/.scitex/orochi/orphan-telemetry/fleet-subs.ndjson``
  one JSON object per line, example:
    {"ts": "2026-04-15T21:00:00Z", "host": "nas", "agent": "head-nas",
     "channels": ["#general","#agent","#progress","#escalation"],
     "canonical_channels": ["#general","#agent","#progress","#escalation"],
     "drift": {"status": "aligned", "missing": [], "extra": []},
     "workspace": "/home/ywatanabe/.scitex/orochi/workspaces/head-nas"}

Usage:
  fleet_sub_snapshot.py                 # all 4 hosts
  fleet_sub_snapshot.py --host nas      # NAS-only (single host debug)
  fleet_sub_snapshot.py --out /tmp/x    # override output directory
  fleet_sub_snapshot.py --stdout        # also print records to stdout

Hosts are reached via SSH (nas/mba/spartan/ywata-note-win) with the same
conventions as fleet-prompt-actuator: BatchMode + ConnectTimeout, local
host gets bash -c fast-path. Unreachable hosts are recorded with
`{"error": "..."}` records so we still see the blackout on dead hosts
(e.g. today's ywata-note-win SSH-dead incident).

Runs standalone (stdlib only). Designed to be called by a systemd user
timer at a slow cadence (e.g. every 5 min) — the launch-time seed map
changes rarely, so high cadence wastes SSH fan-out and hub quota.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

FLEET_HOSTS = ("nas", "mba", "spartan", "ywata-note-win")
DEFAULT_OUT_DIR = Path.home() / ".scitex" / "orochi" / "runtime" / "orphan-telemetry"
# Canonical source of truth: dotfiles/src/.scitex/orochi/shared/agents/<name>/src_mcp.json
CANONICAL_AGENTS_DIR = (
    Path.home() / ".dotfiles" / "src" / ".scitex" / "orochi" / "shared" / "agents"
)
# `find` is portable across bash/zsh on Linux + macOS. The earlier bash-glob
# form `for f in ~/.scitex/orochi/runtime/workspaces/*/.mcp.json` returned empty on
# MBA/Spartan/WSL because non-matching glob behavior differs between shells
# with nullglob unset. `find` sidesteps the whole issue.
WORKSPACES_FIND_CMD = (
    "find ~/.scitex/orochi/runtime/workspaces -maxdepth 3 -name .mcp.json 2>/dev/null"
)
# Live tmux sessions on the target host. Used to classify drift records as
# `stale_workspace` (no live tmux session for this agent on this host) vs
# genuine `drift` (agent is running but its runtime .mcp.json differs from
# canonical). Stale workspaces are multi-host-era leftovers that are not
# actively running; their drift is cosmetic and not actionable.
TMUX_LIST_CMD = "tmux list-sessions -F '#{session_name}' 2>/dev/null"

_HOSTNAME_TO_FLEET_NAME = {
    "dxp480tplus-994": "nas",
    "yusukes-macbook-air": "mba",
    "yusukes-macbook-air.local": "mba",
}


def _local_fleet_name() -> str:
    env = os.environ.get("SCITEX_HEALER_SELF_HOST", "").strip()
    if env:
        return env
    raw = socket.gethostname().split(".")[0].lower()
    if raw.startswith("spartan"):
        return "spartan"
    return _HOSTNAME_TO_FLEET_NAME.get(raw, raw)


def _ssh(host: str, cmd: str, timeout: int = 15) -> tuple[str, str, int]:
    """Run `cmd` locally (bash -c) or on a remote host (via ssh).

    For the remote path we pass `cmd` as a **single** trailing argument to
    ssh. OpenSSH concatenates all trailing argv with spaces into a single
    command string which the remote shell then parses. If we instead pass
    `['bash', '-c', cmd]`, ssh re-joins them into `bash -c cmd arg1 arg2…`
    and the remote shell sees `-c` followed by only the FIRST word of cmd,
    making the rest become positional parameters — find flags get eaten as
    $0, $1, … and the command silently does nothing. Been there.
    """
    if host == _local_fleet_name():
        proc = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    else:
        proc = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", host, cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    return (proc.stdout or "", proc.stderr or "", proc.returncode)


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def list_workspaces(host: str) -> list[str]:
    """Return paths of all `.mcp.json` files under that host's workspaces dir."""
    out, _, rc = _ssh(host, WORKSPACES_FIND_CMD)
    if rc != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def list_live_tmux_sessions(host: str) -> set[str]:
    """Return the set of tmux session names currently alive on the host.

    Used by the drift classifier to distinguish a stale workspace
    (.mcp.json exists but no agent is running it) from a genuine
    drift (.mcp.json differs from canonical AND the agent is live).
    Empty set on ssh failure or if no tmux server is running —
    callers treat this as "conservatively mark everything stale".
    """
    out, _, rc = _ssh(host, TMUX_LIST_CMD)
    if rc != 0:
        return set()
    return {line.strip() for line in out.splitlines() if line.strip()}


def read_mcp_json(host: str, path: str) -> dict | None:
    """Cat the .mcp.json on a host and return parsed JSON (or None on failure)."""
    # Use single-quoted path to avoid shell expansion surprises
    out, _, rc = _ssh(host, f"cat '{path}'")
    if rc != 0 or not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def extract_channels(mcp: dict) -> tuple[str, list[str]]:
    """Pull the agent name + channel list out of a parsed .mcp.json.

    Returns (agent_name, channels). Missing fields become empty strings /
    lists — callers should tolerate that rather than raise.
    """
    env = mcp.get("mcpServers", {}).get("scitex-orochi", {}).get("env", {})
    agent = env.get("SCITEX_OROCHI_AGENT", "")
    raw_channels = env.get("SCITEX_OROCHI_CHANNELS", "")
    channels = [c.strip() for c in raw_channels.split(",") if c.strip()]
    return (agent, channels)


def load_canonical_channels(agent_name: str) -> list[str] | None:
    """Read the canonical channel list from dotfiles/src_mcp.json for an agent.

    Returns None if no canonical config exists for that agent (e.g. legacy
    workspace that was never in the dotfiles source of truth — stale).
    """
    src_path = CANONICAL_AGENTS_DIR / agent_name / "src_mcp.json"
    if not src_path.exists():
        return None
    try:
        mcp = json.loads(src_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    _, channels = extract_channels(mcp)
    return channels


def classify_drift(
    runtime: list[str],
    canonical: list[str] | None,
    live: bool | None = None,
) -> dict:
    """Diff a runtime channel list against the canonical source of truth.

    Returns a dict with keys:
      status:  'aligned' | 'drift' | 'stale_workspace' | 'no_canonical'
      missing: channels present in canonical but NOT runtime (most critical —
               this is the orphan-class signature)
      extra:   channels present in runtime but NOT canonical (usually benign,
               but can indicate a bad manual edit)
      live:    propagated through when caller knows tmux state (True/False
               for live vs dead) or None when unknown.

    ``live=False`` combined with a content difference classifies as
    ``stale_workspace`` instead of ``drift`` — these are legacy workspace
    dirs (e.g. NAS's left-over head-mba/head-spartan workspaces from the
    earlier multi-host fleet-lead era) whose .mcp.json no longer reflects
    anything the hub cares about. Cosmetic diff, not actionable.
    """
    if canonical is None:
        return {
            "status": "no_canonical",
            "missing": [],
            "extra": runtime,
            "live": live,
        }
    runtime_set = set(runtime)
    canonical_set = set(canonical)
    missing = sorted(canonical_set - runtime_set)
    extra = sorted(runtime_set - canonical_set)
    if not missing and not extra:
        status = "aligned"
    elif live is False:
        # Differs from canonical but no agent is actually running here —
        # the file on disk is a museum piece, not a live config.
        status = "stale_workspace"
    else:
        status = "drift"
    return {"status": status, "missing": missing, "extra": extra, "live": live}


def snapshot_host(host: str) -> list[dict]:
    """Return a list of NDJSON records for every workspace on the host.

    Each record includes a ``drift`` sub-dict comparing the on-disk channel
    list against the canonical ``src_mcp.json`` from dotfiles. Drift records
    are **candidates**, not confirmed orphans — a stale workspace .mcp.json
    does not imply the live MCP bridge has a stale subscription set (the
    bridge reads config at launch and may have been launched with a
    different snapshot than what's currently on disk, or may have
    dynamically subscribed via the hub's runtime API after launch).
    Downstream consumers must cross-reference with actual hub traffic
    patterns before acting on a drift record.
    """
    ts = _now_utc_iso()
    try:
        paths = list_workspaces(host)
    except subprocess.TimeoutExpired:
        return [
            {
                "ts": ts,
                "host": host,
                "error": "ssh timeout listing workspaces",
            }
        ]
    except Exception as e:
        return [
            {
                "ts": ts,
                "host": host,
                "error": f"{type(e).__name__}: {e}",
            }
        ]

    if not paths:
        return [
            {
                "ts": ts,
                "host": host,
                "error": "no .mcp.json workspaces found (host dead or unconfigured)",
            }
        ]

    # Pull live tmux sessions once per host so the per-workspace loop can
    # cheaply look up whether this agent is actually running.
    try:
        live_sessions = list_live_tmux_sessions(host)
    except subprocess.TimeoutExpired:
        live_sessions = set()
    except Exception:
        live_sessions = set()

    records: list[dict] = []
    for path in paths:
        mcp = read_mcp_json(host, path)
        if mcp is None:
            records.append(
                {
                    "ts": ts,
                    "host": host,
                    "workspace": path,
                    "error": "cat/parse failed",
                }
            )
            continue
        agent, channels = extract_channels(mcp)
        workspace_dir = path.rsplit("/", 1)[0]
        canonical = load_canonical_channels(agent) if agent else None
        # `live` is True/False when we successfully enumerated tmux
        # sessions; None when the tmux list failed (don't claim dead
        # agents are stale just because we couldn't check).
        if not live_sessions and agent:
            live = None
        elif agent:
            live = agent in live_sessions
        else:
            live = None
        drift = classify_drift(channels, canonical, live=live)
        records.append(
            {
                "ts": ts,
                "host": host,
                "agent": agent or "<unknown>",
                "channels": channels,
                "canonical_channels": canonical,
                "live": live,
                "drift": drift,
                "workspace": workspace_dir,
            }
        )
    return records


def write_ndjson(records: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="fleet_sub_snapshot")
    ap.add_argument(
        "--host",
        action="append",
        default=[],
        help="restrict to one host (repeatable); default: all",
    )
    ap.add_argument(
        "--out",
        default=str(DEFAULT_OUT_DIR),
        help="output directory (default: ~/.scitex/orochi/orphan-telemetry)",
    )
    ap.add_argument(
        "--stdout",
        action="store_true",
        help="also emit NDJSON to stdout (default: file only)",
    )
    args = ap.parse_args(argv[1:])

    hosts = args.host or list(FLEET_HOSTS)
    out_dir = Path(args.out).expanduser()
    out_path = out_dir / "fleet-subs.ndjson"

    all_records: list[dict] = []
    for host in hosts:
        records = snapshot_host(host)
        all_records.extend(records)

    write_ndjson(all_records, out_path)

    if args.stdout:
        for r in all_records:
            print(json.dumps(r, ensure_ascii=False))

    ok_n = sum(1 for r in all_records if "error" not in r)
    err_n = sum(1 for r in all_records if "error" in r)
    drift_n = sum(
        1 for r in all_records if "drift" in r and r["drift"].get("status") == "drift"
    )
    stale_n = sum(
        1
        for r in all_records
        if "drift" in r and r["drift"].get("status") == "stale_workspace"
    )
    print(
        f"fleet_sub_snapshot: {ok_n} ok, {drift_n} live-drift, "
        f"{stale_n} stale-workspace, {err_n} errors, wrote {out_path}",
        file=sys.stderr,
    )

    # Exit 0 if at least one host returned at least one good record;
    # exit 1 if every host failed. Cron-friendly: systemd alerts on rc!=0.
    # Drift candidates are NOT treated as errors — they're informational
    # pending human (or downstream probe) review.
    return 0 if ok_n > 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
