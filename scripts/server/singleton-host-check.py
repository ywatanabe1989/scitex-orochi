#!/usr/bin/env python3
"""singleton-host-check.py — Option C interim for issue #250.

Reads singleton agent YAML files from the shared agents directory, extracts
their ``host:`` priority lists, then queries the Orochi hub registry to
determine where each agent is currently running.  When an agent is on a
lower-priority host but a higher-priority host is alive (reachable via SSH
or confirmed online via the hub registry), the script posts a warning to
#heads.

Designed to run as a cron job every 5–10 minutes:

    */5 * * * * /path/to/singleton-host-check.py --post

Without ``--post`` it prints the report to stdout only (dry-run mode).

References
----------
* Issue #250 — bug(singleton-scheduler): agent host-priority not enforced
* Design option (C) — cron-based interim check
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

log = logging.getLogger("singleton-host-check")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SHARED_AGENTS_DIR = Path.home() / ".scitex" / "orochi" / "shared" / "agents"
HUB_URL = os.environ.get("SCITEX_OROCHI_HUB_URL", "https://scitex-orochi.com")
HUB_TOKEN = os.environ.get("SCITEX_OROCHI_TOKEN", "")
HEADS_CHANNEL = "#heads"

# Hosts we consider "reachable" if they appear in the hub registry with
# liveness != offline within the last N minutes.  SSH check is a fallback.
LIVENESS_ACTIVE_STATES = {"online", "busy", "idle"}

# ---------------------------------------------------------------------------
# YAML loader (plain stdlib if PyYAML missing)
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        return yaml.safe_load(text) or {}
    # Minimal YAML subset: key: value and list items (- item)
    result: dict = {}
    current_key: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line.startswith("  ") or line.startswith("\t"):
            stripped = line.strip()
            if stripped.startswith("- ") and current_key == "host":
                result.setdefault("host", []).append(stripped[2:].strip())
        else:
            if ":" in line:
                k, _, v = line.partition(":")
                current_key = k.strip()
                val = v.strip()
                if val:
                    result[current_key] = val
    return result


# ---------------------------------------------------------------------------
# Collect singleton specs
# ---------------------------------------------------------------------------


def _collect_specs(agents_dir: Path | None = None) -> list[dict]:
    """Return list of {name, host_priority, spec_path} for each singleton."""
    search_dir = agents_dir or SHARED_AGENTS_DIR
    specs = []
    if not search_dir.exists():
        log.warning("shared agents dir not found: %s", search_dir)
        return specs

    for spec_file in sorted(search_dir.rglob("*.yaml")):
        try:
            data = _load_yaml(spec_file)
        except Exception as exc:  # stx-allow: fallback (reason: malformed YAML — skip and continue scanning)
            log.debug("skip %s: %s", spec_file, exc)
            continue

        spec = data.get("spec", data)
        host_val = spec.get("host", [])
        if isinstance(host_val, str):
            host_val = [host_val] if host_val else []
        host_priority: list[str] = [h.strip() for h in host_val if h]
        if len(host_priority) <= 1:
            # Single-host or no-host agents have no preemption concern.
            continue

        agent_name = spec_file.parent.name
        specs.append({
            "name": agent_name,
            "host_priority": host_priority,
            "spec_path": str(spec_file),
        })
    return specs


# ---------------------------------------------------------------------------
# Hub registry query
# ---------------------------------------------------------------------------


def _fetch_agents() -> list[dict]:
    """GET /api/agents/ and return list of agent dicts."""
    try:
        import urllib.request
        url = f"{HUB_URL}/api/agents/?token={HUB_TOKEN}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as exc:  # stx-allow: fallback (reason: hub unreachable — return empty list, no false positives)
        log.warning("Failed to fetch agents from hub: %s", exc)
        return []


def _build_machine_map(agents: list[dict]) -> dict[str, str]:
    """Return {agent_name: machine} for live agents."""
    result: dict[str, str] = {}
    for a in agents:
        name = a.get("name", "")
        machine = a.get("machine", "")
        liveness = a.get("liveness", "offline")
        if name and machine and liveness in LIVENESS_ACTIVE_STATES:
            # Strip agent- prefix so we match yaml names like "mgr-scitex"
            bare = name.removeprefix("agent-")
            result[bare] = machine
    return result


def _online_machines(agents: list[dict]) -> set[str]:
    """Return set of machines that have at least one live agent."""
    machines: set[str] = set()
    for a in agents:
        if a.get("liveness", "offline") in LIVENESS_ACTIVE_STATES:
            m = a.get("machine", "")
            if m:
                machines.add(m)
    return machines


# ---------------------------------------------------------------------------
# SSH reachability check (fallback)
# ---------------------------------------------------------------------------


def _ssh_reachable(host: str, timeout: int = 5) -> bool:
    try:
        result = subprocess.run(
            ["ssh", "-o", f"ConnectTimeout={timeout}", "-o", "BatchMode=yes",
             "-o", "StrictHostKeyChecking=no", host, "hostname"],
            capture_output=True,
            timeout=timeout + 2,
        )
        return result.returncode == 0
    except Exception:  # stx-allow: fallback (reason: SSH failure — treat host as unreachable)
        return False


# ---------------------------------------------------------------------------
# Check logic
# ---------------------------------------------------------------------------


def check_placements(
    specs: list[dict],
    machine_map: dict[str, str],
    online_machines: set[str],
    *,
    ssh_fallback: bool = False,
) -> list[dict]:
    """Return list of misplacement warnings."""
    warnings: list[dict] = []

    for spec in specs:
        name = spec["name"]
        priority_list = spec["host_priority"]
        current_machine = machine_map.get(name)

        if current_machine is None:
            log.debug("%s not found in live registry — skipping", name)
            continue

        # Normalise: strip @host suffix the registry might add
        current_machine_bare = current_machine.split("@")[-1].split(".")[0]

        # Find where this agent sits in the priority list
        try:
            current_rank = next(
                i for i, h in enumerate(priority_list)
                if h.lower() == current_machine_bare.lower()
            )
        except StopIteration:
            log.debug(
                "%s on machine %s which is not in its priority list %s",
                name, current_machine, priority_list,
            )
            current_rank = len(priority_list)

        if current_rank == 0:
            log.debug("%s on top-priority host %s — OK", name, current_machine)
            continue

        # Check whether any higher-priority host is alive
        for rank, host in enumerate(priority_list[:current_rank]):
            alive = host in online_machines
            if not alive and ssh_fallback:
                alive = _ssh_reachable(host)
                if alive:
                    online_machines.add(host)  # cache

            if alive:
                warnings.append({
                    "agent": name,
                    "current_machine": current_machine,
                    "current_rank": current_rank + 1,
                    "preferred_host": host,
                    "preferred_rank": rank + 1,
                    "priority_list": priority_list,
                })
                break  # report only the highest available preferred host

    return warnings


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _format_report(warnings: list[dict]) -> str:
    if not warnings:
        return ""
    lines = ["[singleton-host-check] placement warnings:"]
    for w in warnings:
        lines.append(
            f"  • {w['agent']}: running on {w['current_machine']} "
            f"(priority #{w['current_rank']}) but {w['preferred_host']} "
            f"(priority #{w['preferred_rank']}) is reachable — "
            f"priority order: {' > '.join(w['priority_list'])}"
        )
    lines.append(
        "Action: ask the healer on the preferred host to claim the singleton "
        "and shut down the lower-priority instance. (#250)"
    )
    return "\n".join(lines)


def _post_to_heads(text: str) -> None:
    try:
        import urllib.request
        data = json.dumps({
            "token": HUB_TOKEN,
            "channel": HEADS_CHANNEL,
            "text": text,
        }).encode()
        req = urllib.request.Request(
            f"{HUB_URL}/api/messages/",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as exc:  # stx-allow: fallback (reason: hub may be unreachable during check)
        log.warning("Failed to post to hub: %s", exc)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--post",
        action="store_true",
        help="Post warnings to #heads (default: dry-run, print only)",
    )
    parser.add_argument(
        "--ssh",
        action="store_true",
        help="Fall back to SSH reachability check for machines not in registry",
    )
    parser.add_argument(
        "--agents-dir",
        default=str(SHARED_AGENTS_DIR),
        help="Path to shared agents directory",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )

    agents_dir = Path(args.agents_dir)

    if not HUB_TOKEN:
        print("ERROR: SCITEX_OROCHI_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    specs = _collect_specs(agents_dir)
    if not specs:
        print("No multi-host singleton specs found — nothing to check.")
        return

    agents = _fetch_agents()
    machine_map = _build_machine_map(agents)
    online_machines = _online_machines(agents)

    warnings = check_placements(
        specs, machine_map, online_machines, ssh_fallback=args.ssh
    )

    report = _format_report(warnings)
    if not report:
        print("All singletons are on their top-priority reachable host.")
        return

    print(report)
    if args.post:
        _post_to_heads(report)
        print("(posted to #heads)")


if __name__ == "__main__":
    main()
