"""Cross-machine version consistency check (#136 Phase 2).

Takes status reports from multiple agents and identifies:
- Version mismatches (Python, Node, Claude, scitex packages)
- Git SHA drift (are machines on the same commit?)
- Missing tools (e.g. bun not installed on spartan)
- Resource alerts (low disk, high memory)

Designed to be called server-side after aggregating statuses from agents
via the Orochi MCP channel.
"""
from __future__ import annotations

from typing import Any


# Fields to compare across machines
COMPARED_VERSION_KEYS = [
    "python",
    "node",
    "claude",
    "git",
    "scitex",
    "scitex-orochi",
    "scitex-dev",
    "scitex-agent-container",
]


def _normalize_version(raw: str) -> str:
    """Normalize version strings for comparison."""
    if not raw or raw == "not-found":
        return raw
    # Strip 'v' prefix (node), suffix parens (claude "2.1.81 (Claude Code)")
    s = raw.strip()
    if s.startswith("v"):
        s = s[1:]
    if "(" in s:
        s = s.split("(")[0].strip()
    return s


def compare_versions(
    statuses: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Compare versions across machines.

    Args:
        statuses: {agent_name: status_dict} where status_dict is from get_machine_status()

    Returns:
        {
            "agents": list of agent names checked,
            "mismatches": list of {key, values: {agent: version}} for keys that differ,
            "consistent": list of keys that match across all agents,
            "missing_tools": list of {tool, missing_on: [agents]}
        }
    """
    agents = list(statuses.keys())
    result: dict[str, Any] = {
        "agents": agents,
        "mismatches": [],
        "consistent": [],
        "missing_tools": [],
    }
    if not agents:
        return result

    # Collect versions per key across agents
    for key in COMPARED_VERSION_KEYS:
        per_agent: dict[str, str] = {}
        for agent in agents:
            versions = statuses.get(agent, {}).get("versions", {})
            raw = versions.get(key, "")
            per_agent[agent] = _normalize_version(raw) if raw else "missing"

        # Identify tools missing on some agents
        missing_on = [a for a, v in per_agent.items() if v in ("missing", "not-found", "")]
        if missing_on and len(missing_on) < len(agents):
            result["missing_tools"].append(
                {"tool": key, "missing_on": missing_on, "available_on": [a for a in agents if a not in missing_on]}
            )
            continue

        # All missing — skip (tool not expected)
        if len(missing_on) == len(agents):
            continue

        # Compare versions
        values = set(per_agent.values())
        if len(values) == 1:
            result["consistent"].append({"key": key, "version": list(values)[0]})
        else:
            result["mismatches"].append({"key": key, "values": per_agent})

    return result


def compare_git_shas(
    statuses: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Compare git SHA across machines for the same repo."""
    agents = list(statuses.keys())
    shas: dict[str, dict[str, str]] = {}
    for agent in agents:
        git = statuses.get(agent, {}).get("git", {})
        shas[agent] = {
            "branch": git.get("branch", "unknown"),
            "sha": git.get("sha", "unknown"),
            "dirty": git.get("dirty", "unknown"),
        }
    unique_shas = set(s["sha"] for s in shas.values())
    return {
        "per_agent": shas,
        "consistent": len(unique_shas) == 1,
        "sha_count": len(unique_shas),
    }


def check_resources(
    statuses: dict[str, dict[str, Any]],
    *,
    memory_threshold: float = 90.0,
    disk_threshold: float = 90.0,
    loadavg_threshold: float = 8.0,
) -> list[dict[str, Any]]:
    """Flag agents with resource issues."""
    alerts: list[dict[str, Any]] = []
    for agent, status in statuses.items():
        res = status.get("resources", {})
        mem = res.get("memory_percent")
        if mem is not None and mem > memory_threshold:
            alerts.append(
                {"agent": agent, "severity": "warning", "metric": "memory", "value": mem, "threshold": memory_threshold}
            )
        disk = res.get("disk_percent")
        if disk is not None and disk > disk_threshold:
            alerts.append(
                {"agent": agent, "severity": "warning", "metric": "disk", "value": disk, "threshold": disk_threshold}
            )
        load = res.get("loadavg_5m")
        if load is not None and load > loadavg_threshold:
            alerts.append(
                {"agent": agent, "severity": "info", "metric": "loadavg_5m", "value": load, "threshold": loadavg_threshold}
            )
    return alerts


def full_report(statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Full cross-machine consistency report."""
    return {
        "agent_count": len(statuses),
        "agents": list(statuses.keys()),
        "versions": compare_versions(statuses),
        "git": compare_git_shas(statuses),
        "resource_alerts": check_resources(statuses),
    }


if __name__ == "__main__":
    import json

    # Demo with mock statuses
    mock_statuses = {
        "head@nas": {
            "versions": {"python": "3.10.15", "node": "v20.18.0", "git": "2.39.5", "claude": "2.1.81 (Claude Code)"},
            "git": {"branch": "main", "sha": "efbe37f", "dirty": "yes"},
            "resources": {"memory_percent": 17.9, "disk_percent": 66.8, "loadavg_5m": 1.65},
        },
        "head@mba": {
            "versions": {"python": "3.11.6", "node": "v22.0.0", "git": "2.42.0", "claude": "2.1.81 (Claude Code)"},
            "git": {"branch": "main", "sha": "efbe37f", "dirty": "no"},
            "resources": {"memory_percent": 45.0, "disk_percent": 82.0, "loadavg_5m": 2.1},
        },
        "head@spartan": {
            "versions": {"python": "3.10.12", "node": "v22.0.0", "git": "2.39.5", "claude": "2.1.81 (Claude Code)"},
            "git": {"branch": "main", "sha": "efbe37f", "dirty": "no"},
            "resources": {"memory_percent": 60.0, "disk_percent": 87.0, "loadavg_5m": 0.5},
        },
    }
    print(json.dumps(full_report(mock_statuses), indent=2))
