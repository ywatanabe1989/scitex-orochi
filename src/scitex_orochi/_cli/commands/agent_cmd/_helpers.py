"""Shared helpers for agent_cmd subcommands."""

from __future__ import annotations

import subprocess
from pathlib import Path

import click
import yaml
from scitex_config._ecosystem import local_state

# ── Constants ──────────────────────────────────────────────────────
AGENTS_DIR = local_state.user_path("orochi", "agents")
WORKSPACES_DIR = Path.home() / ".scitex" / "orochi" / "workspaces"
SETUP_SCRIPT = Path.home() / "proj" / "scitex-orochi" / "scripts" / "setup-workspace.sh"
DEV_CHANNEL_CONFIRM_DELAY = 8  # seconds before pressing Enter


# ── Helpers ────────────────────────────────────────────────────────


def _list_agent_names() -> list[str]:
    """Return sorted list of agent names from AGENTS_DIR."""
    if not AGENTS_DIR.is_dir():
        return []
    return sorted(
        d.name
        for d in AGENTS_DIR.iterdir()
        if d.is_dir() and d.name != "legacy" and not d.name.startswith("_")
    )


def _load_agent_config(name: str) -> dict:
    """Load config.yaml for an agent, falling back to derived defaults."""
    agent_dir = AGENTS_DIR / name
    config_file = agent_dir / "config.yaml"

    if config_file.exists():
        with open(config_file) as f:
            return yaml.safe_load(f) or {}

    # Try to extract metadata from the agent-container YAML if present
    ac_yaml = agent_dir / f"{name}.yaml"
    if ac_yaml.exists():
        return _extract_config_from_ac_yaml(ac_yaml)

    # Derive from agent name
    return _derive_config(name)


def _extract_config_from_ac_yaml(yaml_path: Path) -> dict:
    """Extract useful config from an agent-container YAML spec."""
    try:
        with open(yaml_path) as f:
            raw = yaml.safe_load(f) or {}
    except Exception:
        return _derive_config(yaml_path.stem)

    meta = raw.get("metadata", {}) or {}
    labels = meta.get("labels", {}) or {}
    spec = raw.get("spec", {}) or {}
    remote = spec.get("remote", {}) or {}
    screen_cfg = spec.get("screen", {}) or {}

    raw_host = (
        remote.get("host")
        or labels.get("machine")
        or _derive_host(meta.get("name", yaml_path.stem))
    )
    # Normalize: if the raw host matches the local machine, use localhost
    host = (
        "localhost" if _is_local(raw_host) or _is_local_machine(raw_host) else raw_host
    )
    return {
        "host": host,
        "user": remote.get("user", ""),
        "role": labels.get("role", "head"),
        "screen_name": screen_cfg.get("name", meta.get("name", yaml_path.stem)),
        "model": spec.get("model", "opus[1m]"),
        "workdir": spec.get("workdir", f"~/.scitex/orochi/workspaces/{yaml_path.stem}"),
    }


def _derive_host(name: str) -> str:
    """Derive SSH host from agent name convention.

    head-mba       -> mba
    head-nas       -> nas
    head-spartan   -> spartan
    head-ywata-note-win -> localhost
    master-ywata-note-win -> localhost
    telegrammer-ywata-note-win -> localhost
    mamba-mba      -> mba
    caduceus-mba   -> mba
    """
    import platform

    # Split off the role prefix (first segment before '-')
    parts = name.split("-", 1)
    if len(parts) < 2:
        return "localhost"

    machine = parts[1]

    # Check if this machine name matches the local hostname
    local_hostname = platform.node()
    # ywata-note-win running on ywata-note-win -> localhost
    if machine == local_hostname or machine in local_hostname:
        return "localhost"

    return machine


def _derive_config(name: str) -> dict:
    """Derive minimal config from agent name."""
    host = _derive_host(name)
    parts = name.split("-", 1)
    role = parts[0] if parts else "head"
    return {
        "host": host,
        "role": role,
        "screen_name": name,
        "model": "opus[1m]",
        "workdir": f"~/.scitex/orochi/workspaces/{name}",
    }


def _is_local(host: str) -> bool:
    """Check if host refers to the local machine."""
    return host in ("localhost", "127.0.0.1", "::1", "")


def _is_local_machine(host: str) -> bool:
    """Check if host matches the local machine's hostname."""
    import platform

    local_hostname = platform.node()
    return host == local_hostname or host in local_hostname or local_hostname in host


def _ssh_prefix(host: str, user: str = "") -> str | None:
    """Return SSH command prefix for remote hosts, None for local."""
    if _is_local(host):
        return None
    target = f"{user}@{host}" if user else host
    return f"ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no {target}"


def _run_cmd(
    cmd: str,
    ssh: str | None = None,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess:
    """Run a command locally or via SSH."""
    if ssh:
        full = f"{ssh} bash -lc {_shell_quote(cmd)}"
    else:
        full = cmd
    return subprocess.run(
        full,
        shell=True,
        capture_output=capture,
        text=True,
        timeout=30,
    )


def _shell_quote(s: str) -> str:
    """Quote a string for shell embedding."""
    return "'" + s.replace("'", "'\"'\"'") + "'"


def _screen_exists(name: str, ssh: str | None = None) -> bool:
    """Check if a screen session exists."""
    cmd = "screen -ls 2>/dev/null"
    if ssh:
        cmd = f"{ssh} {cmd}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
    return f".{name}\t" in result.stdout or f".{name} " in result.stdout


def _screen_quit(name: str, ssh: str | None = None) -> bool:
    """Quit a screen session. Returns True if successful."""
    cmd = f"screen -S {name} -X quit"
    if ssh:
        cmd = f"{ssh} {cmd}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
    return result.returncode == 0


def _setup_workspace(name: str, ssh: str | None = None) -> bool:
    """Run setup-workspace.sh for an agent. Returns True if successful."""
    # For local: run the script directly
    # For remote: the script must exist on the remote too
    script = str(SETUP_SCRIPT)
    if ssh:
        # On remote, the setup-workspace.sh should be at the same relative path
        cmd = f"bash -l -c '{script} {name}'"
        result = subprocess.run(
            f"{ssh} {_shell_quote(cmd)}",
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    else:
        result = subprocess.run(
            f"bash {script} {name}",
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

    if result.returncode != 0:
        click.echo(
            f"  Warning: setup-workspace.sh failed: {result.stderr.strip()}", err=True
        )
        return False

    if result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            click.echo(f"  {line}")
    return True
