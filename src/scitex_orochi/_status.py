"""Machine status reporting for Orochi (#136 Phase 1).

Reports per-machine:
- Identity: hostname, username, uptime, working directory
- Versions: Python, Node, Claude Code, key scitex packages, git SHAs
- Resources: CPU%, memory%, disk%
- Processes: claude, bun, screen sessions
- Agents: locally running Orochi agents

Designed to be called via MCP tool `orochi_machine_status()`.
"""
from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


def _run(cmd: list[str], timeout: float = 5.0) -> str:
    """Run a command, return stdout (or empty string on failure)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return ""


def get_identity() -> dict[str, Any]:
    """Machine identity: hostname, user, uptime, workdir."""
    try:
        with open("/proc/uptime") as f:
            uptime_seconds = float(f.read().split()[0])
    except (OSError, ValueError):
        uptime_seconds = 0.0
    return {
        "hostname": socket.gethostname(),
        "username": os.environ.get("USER", ""),
        "home": os.path.expanduser("~"),
        "cwd": os.getcwd(),
        "uptime_seconds": uptime_seconds,
        "platform": platform.platform(),
        "python_version": platform.python_version(),
    }


def get_versions() -> dict[str, str]:
    """Tool versions: Node, Claude Code, git, bun, Python packages."""
    versions: dict[str, str] = {
        "python": platform.python_version(),
        "node": _run(["node", "--version"]) or "not-found",
        "bun": _run(["bun", "--version"]) or "not-found",
        "git": _run(["git", "--version"]).replace("git version ", "") or "not-found",
        "claude": _run(["claude", "--version"]) or "not-found",
    }
    # Try to get scitex package versions via importlib.metadata
    try:
        from importlib.metadata import version, PackageNotFoundError

        for pkg in [
            "scitex",
            "scitex-io",
            "scitex-stats",
            "scitex-orochi",
            "scitex-dev",
            "scitex-agent-container",
        ]:
            try:
                versions[pkg] = version(pkg)
            except PackageNotFoundError:
                pass
    except ImportError:
        pass
    return versions


def get_resources() -> dict[str, Any]:
    """System resources: CPU, memory, disk."""
    result: dict[str, Any] = {}
    # Memory from /proc/meminfo
    try:
        meminfo: dict[str, int] = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip().split()[0]
                    try:
                        meminfo[key] = int(val)
                    except ValueError:
                        pass
        total_kb = meminfo.get("MemTotal", 0)
        avail_kb = meminfo.get("MemAvailable", 0)
        if total_kb > 0:
            result["memory_total_gb"] = round(total_kb / 1024 / 1024, 1)
            result["memory_available_gb"] = round(avail_kb / 1024 / 1024, 1)
            result["memory_percent"] = round(100 * (1 - avail_kb / total_kb), 1)
    except OSError:
        pass
    # Load average from /proc/loadavg
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
            result["loadavg_1m"] = float(parts[0])
            result["loadavg_5m"] = float(parts[1])
            result["loadavg_15m"] = float(parts[2])
    except (OSError, ValueError, IndexError):
        pass
    # Disk usage for home directory
    try:
        usage = shutil.disk_usage(os.path.expanduser("~"))
        result["disk_total_gb"] = round(usage.total / 1024**3, 1)
        result["disk_free_gb"] = round(usage.free / 1024**3, 1)
        result["disk_percent"] = round(100 * usage.used / usage.total, 1)
    except OSError:
        pass
    return result


def get_processes() -> dict[str, Any]:
    """Running processes relevant to Orochi agents."""
    procs: dict[str, Any] = {
        "claude_running": False,
        "bun_running": False,
        "screen_sessions": [],
        "orochi_agents": [],
    }
    try:
        # Read /proc to find running processes
        for pid_dir in Path("/proc").iterdir():
            if not pid_dir.name.isdigit():
                continue
            try:
                with open(pid_dir / "cmdline", "rb") as f:
                    cmdline = f.read().replace(b"\x00", b" ").decode("utf-8", "ignore")
            except OSError:
                continue
            if not cmdline:
                continue
            cmd_lower = cmdline.lower()
            if "claude" in cmd_lower and "/bin/claude" in cmdline or "claude --" in cmdline:
                procs["claude_running"] = True
            if "bun" in cmd_lower and "mcp_channel" in cmdline:
                procs["bun_running"] = True
                # Extract agent name from env via /proc/<pid>/environ
                try:
                    with open(pid_dir / "environ", "rb") as ef:
                        env_data = ef.read().decode("utf-8", "ignore")
                    for kv in env_data.split("\x00"):
                        if kv.startswith("SCITEX_OROCHI_AGENT="):
                            agent_name = kv.split("=", 1)[1]
                            if agent_name and agent_name not in procs["orochi_agents"]:
                                procs["orochi_agents"].append(agent_name)
                except OSError:
                    pass
    except OSError:
        pass
    # Screen sessions
    screen_out = _run(["screen", "-ls"])
    for line in screen_out.splitlines():
        line = line.strip()
        if "." in line and ("Detached" in line or "Attached" in line):
            # Format: "12345.name\t(date)\t(state)"
            procs["screen_sessions"].append(line.split("\t")[0])
    return procs


def get_git_info(project_path: str = "~/proj/scitex-orochi") -> dict[str, str]:
    """Git status for a key project path."""
    path = os.path.expanduser(project_path)
    if not os.path.isdir(os.path.join(path, ".git")):
        return {}
    result = {
        "path": path,
        "branch": _run(["git", "-C", path, "rev-parse", "--abbrev-ref", "HEAD"]),
        "sha": _run(["git", "-C", path, "rev-parse", "--short", "HEAD"]),
        "dirty": "yes" if _run(["git", "-C", path, "status", "--porcelain"]) else "no",
    }
    return result


def get_machine_status() -> dict[str, Any]:
    """Aggregate full machine status report."""
    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "identity": get_identity(),
        "versions": get_versions(),
        "resources": get_resources(),
        "processes": get_processes(),
        "git": get_git_info(),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(get_machine_status(), indent=2))
