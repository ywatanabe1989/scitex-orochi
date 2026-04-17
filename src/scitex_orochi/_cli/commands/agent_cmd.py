"""CLI commands: scitex-orochi {launch,restart,stop,status} for agent lifecycle.

Direct agent lifecycle management using agent definitions from
``~/.scitex/orochi/shared/agents/<name>/`` or
``~/.scitex/orochi/<host>/agents/<name>/`` (see
``~/.scitex/orochi/README.md``; dotfiles commit 68bd1592).
Each agent directory may contain:
  - config.yaml  (host, role, channels, etc.)
  - .mcp.json.example  (MCP config template with $HOME etc.)
  - CLAUDE.md  (agent-specific instructions)
  - <name>.yaml  (legacy agent-container spec, used for metadata)

Launch flow:
  1. Read agent definition
  2. Determine host (from config.yaml or derive from name)
  3. SSH to host (or local if localhost)
  4. Run setup-workspace.sh to prepare workspace
  5. Start screen session with claude
  6. After delay, press Enter to confirm dev channel dialog
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import click
import yaml

from scitex_orochi._cli._helpers import EXAMPLES_HEADER

# ── Constants ──────────────────────────────────────────────────────
# Agent definition lookup roots, in order of precedence (dotfiles 68bd1592):
#   1. ~/.scitex/orochi/<host>/agents/     (host-specific override)
#   2. ~/.scitex/orochi/shared/agents/     (shared template)
_OROCHI_ROOT = Path.home() / ".scitex" / "orochi"
SHARED_AGENTS_DIR = _OROCHI_ROOT / "shared" / "agents"
# Deployed per-agent workdir (runtime, gitignored).
WORKSPACES_DIR = _OROCHI_ROOT / "runtime" / "workspaces"
SETUP_SCRIPT = Path.home() / "proj" / "scitex-orochi" / "scripts" / "setup-workspace.sh"
DEV_CHANNEL_CONFIRM_DELAY = 8  # seconds before pressing Enter


def _host_agents_dir() -> Path:
    """Resolve ``<host>/agents/`` using the canonical hostname rule."""
    import os
    import socket

    host = os.environ.get("SCITEX_OROCHI_HOSTNAME", "").strip()
    if not host:
        try:
            host = socket.gethostname().split(".")[0]
        except Exception:
            host = ""
    if not host:
        return _OROCHI_ROOT / "_no_host_"
    return _OROCHI_ROOT / host / "agents"


def _candidate_agents_dirs() -> list[Path]:
    """Ordered candidate roots for agent-definition lookup."""
    return [_host_agents_dir(), SHARED_AGENTS_DIR]


def _resolve_agent_dir(name: str) -> Path:
    """Return the first existing agent definition dir for ``name``.

    Falls back to the canonical shared-layout path so callers that then
    try to open subfiles get a consistent "not found" error pointing to
    the expected location.
    """
    for root in _candidate_agents_dirs():
        candidate = root / name
        if candidate.is_dir():
            return candidate
    return SHARED_AGENTS_DIR / name


# ── Helpers ────────────────────────────────────────────────────────


def _list_agent_names() -> list[str]:
    """Return sorted list of agent names across canonical roots."""
    names: set[str] = set()
    for root in _candidate_agents_dirs():
        if not root.is_dir():
            continue
        for d in root.iterdir():
            if not d.is_dir():
                continue
            if d.name in ("legacy", "legacy-agents") or d.name.startswith("_"):
                continue
            names.add(d.name)
    return sorted(names)


def _load_agent_config(name: str) -> dict:
    """Load config.yaml for an agent, falling back to derived defaults."""
    agent_dir = _resolve_agent_dir(name)
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
        "workdir": spec.get(
            "workdir",
            f"~/.scitex/orochi/runtime/workspaces/{yaml_path.stem}",
        ),
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
        "workdir": f"~/.scitex/orochi/runtime/workspaces/{name}",
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


def _launch_agent(name: str, dry_run: bool = False, force: bool = False) -> bool:
    """Launch a single agent. Returns True on success."""
    agent_dir = _resolve_agent_dir(name)
    if not agent_dir.is_dir():
        click.echo(f"Error: agent directory not found: {agent_dir}", err=True)
        return False

    cfg = _load_agent_config(name)
    host = cfg.get("host", "localhost")
    user = cfg.get("user", "")
    screen_name = cfg.get("screen_name", name)
    ssh = _ssh_prefix(host, user)
    is_local = _is_local(host)

    click.echo(f"Agent: {name}")
    click.echo(f"  Host: {host} ({'local' if is_local else 'remote'})")
    click.echo(f"  Screen: {screen_name}")

    # Check for existing session
    try:
        if _screen_exists(screen_name, ssh):
            if force:
                click.echo(f"  Stopping existing session '{screen_name}'...")
                _screen_quit(screen_name, ssh)
                time.sleep(1)
            else:
                click.echo(
                    f"  Error: screen '{screen_name}' already running.\n"
                    f"  Use --force to restart, or: scitex-orochi restart {name}",
                    err=True,
                )
                return False
    except subprocess.TimeoutExpired:
        click.echo(f"  Error: timeout checking screen on {host}", err=True)
        return False

    # Build the launch command
    workspace = f"~/.scitex/orochi/runtime/workspaces/{name}"
    claude_cmd = (
        f"cd {workspace} && "
        f"exec claude "
        f"--dangerously-skip-permissions "
        f"--dangerously-load-development-channels server:scitex-orochi"
    )
    screen_cmd = f"screen -dmS {screen_name} bash -lc '{claude_cmd}'"

    # Build the confirm command (press Enter after delay)
    confirm_cmd = f"screen -S {screen_name} -X stuff $'\\r'"

    if dry_run:
        click.echo("  [dry-run] Would execute:")
        if ssh:
            click.echo(f"    {ssh} bash -lc 'setup-workspace.sh {name}'")
            click.echo(f"    {ssh} {screen_cmd}")
        else:
            click.echo(f"    bash {SETUP_SCRIPT} {name}")
            click.echo(f"    {screen_cmd}")
        click.echo(f"    sleep {DEV_CHANNEL_CONFIRM_DELAY}")
        click.echo(f"    {confirm_cmd}")
        return True

    # Step 1: Setup workspace
    click.echo("  Setting up workspace...")
    _setup_workspace(name, ssh)

    # Step 2: Ensure workspace directory exists (even if setup-workspace.sh skipped)
    mkdir_cmd = f"mkdir -p {workspace}/.claude"
    if ssh:
        subprocess.run(f"{ssh} {_shell_quote(mkdir_cmd)}", shell=True, timeout=10)
    else:
        subprocess.run(mkdir_cmd, shell=True, timeout=10)

    # Step 3: Copy CLAUDE.md to workspace if it exists in agent dir
    claude_md = agent_dir / "CLAUDE.md"
    if claude_md.exists():
        if ssh:
            # scp CLAUDE.md to remote workspace
            target = f"{user}@{host}" if user else host
            expanded_ws = workspace.replace(
                "~", f"/home/{user}" if user else str(Path.home())
            )
            subprocess.run(
                f"scp -o ConnectTimeout=5 {claude_md} {target}:{expanded_ws}/CLAUDE.md",
                shell=True,
                capture_output=True,
                timeout=15,
            )
        # For local, setup-workspace.sh already handles this

    # Step 4: Start screen session
    click.echo("  Starting screen session...")
    if ssh:
        result = subprocess.run(
            f"{ssh} {_shell_quote(screen_cmd)}",
            shell=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    else:
        result = subprocess.run(
            screen_cmd, shell=True, capture_output=True, text=True, timeout=15
        )

    if result.returncode != 0:
        click.echo(f"  Error: screen start failed: {result.stderr.strip()}", err=True)
        return False

    # Step 5: Wait and confirm dev channel dialog
    click.echo(f"  Waiting {DEV_CHANNEL_CONFIRM_DELAY}s for dev-channel dialog...")
    time.sleep(DEV_CHANNEL_CONFIRM_DELAY)

    click.echo("  Confirming dev-channel dialog...")
    if ssh:
        subprocess.run(f"{ssh} {_shell_quote(confirm_cmd)}", shell=True, timeout=10)
    else:
        subprocess.run(confirm_cmd, shell=True, timeout=10)

    # Verify
    time.sleep(1)
    try:
        if _screen_exists(screen_name, ssh):
            click.echo(click.style(f"  Launched: {name}", fg="green"))
            return True
        else:
            click.echo("  Error: screen session disappeared after launch", err=True)
            return False
    except subprocess.TimeoutExpired:
        click.echo(f"  Warning: could not verify screen on {host}", err=True)
        return True  # Optimistic -- launch command succeeded


def _stop_agent(name: str, force: bool = False) -> bool:
    """Stop a single agent. Returns True on success."""
    cfg = _load_agent_config(name)
    host = cfg.get("host", "localhost")
    user = cfg.get("user", "")
    screen_name = cfg.get("screen_name", name)
    ssh = _ssh_prefix(host, user)

    try:
        if not _screen_exists(screen_name, ssh):
            if force:
                click.echo(f"  {name}: not running (skipped)")
                return True
            click.echo(f"  {name}: not running", err=True)
            return False
    except subprocess.TimeoutExpired:
        click.echo(f"  {name}: timeout checking {host}", err=True)
        return False

    ok = _screen_quit(screen_name, ssh)
    if ok:
        click.echo(click.style(f"  Stopped: {name}", fg="yellow"))
    else:
        click.echo(f"  Error: could not stop {name}", err=True)
    return ok


def _agent_status_row(name: str) -> dict:
    """Get status info for a single agent."""
    cfg = _load_agent_config(name)
    host = cfg.get("host", "localhost")
    user = cfg.get("user", "")
    screen_name = cfg.get("screen_name", name)
    role = cfg.get("role", "unknown")
    ssh = _ssh_prefix(host, user)

    status = "unknown"
    try:
        if _screen_exists(screen_name, ssh):
            status = "running"
        else:
            status = "stopped"
    except (subprocess.TimeoutExpired, Exception):
        status = "unreachable"

    return {
        "name": name,
        "host": host,
        "role": role,
        "screen": screen_name,
        "status": status,
    }


# ── CLI Commands ───────────────────────────────────────────────────


@click.command(
    "agent-launch",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi agent-launch head-mba\n"
    + "  scitex-orochi agent-launch head-mba --force\n"
    + "  scitex-orochi agent-launch --all\n"
    + "  scitex-orochi agent-launch --all --dry-run\n",
)
@click.argument("name", required=False)
@click.option("--all", "launch_all", is_flag=True, help="Launch all defined agents.")
@click.option("--dry-run", is_flag=True, help="Print commands without executing.")
@click.option(
    "--force", is_flag=True, help="Stop existing session first, then relaunch."
)
def agent_launch(
    name: str | None, launch_all: bool, dry_run: bool, force: bool
) -> None:
    """Launch an agent by name, or all agents with --all.

    Reads agent definition from ~/.scitex/orochi/<host>/agents/<name>/ or
    ~/.scitex/orochi/shared/agents/<name>/. Creates/uses
    ~/.scitex/orochi/runtime/workspaces/<name>/ as the workdir and starts a
    screen session with claude.
    """
    if not launch_all and not name:
        click.echo("Error: provide an agent NAME or use --all.", err=True)
        sys.exit(2)

    if launch_all:
        agents = _list_agent_names()
        if not agents:
            click.echo(
                "No agents found in ~/.scitex/orochi/{shared,<host>}/agents/.",
                err=True,
            )
            sys.exit(1)

        click.echo(f"Launching {len(agents)} agent(s)...\n")
        results = []
        for agent_name in agents:
            click.echo(f"\n{'=' * 50}")
            ok = _launch_agent(agent_name, dry_run=dry_run, force=force)
            results.append((agent_name, ok))

        click.echo(f"\n{'=' * 50}")
        launched = sum(1 for _, ok in results if ok)
        click.echo(f"\nDone: {launched}/{len(results)} agent(s) launched.")
        if launched < len(results):
            sys.exit(1)
        return

    assert name is not None
    ok = _launch_agent(name, dry_run=dry_run, force=force)
    if not ok:
        sys.exit(1)


@click.command(
    "agent-restart",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi agent-restart head-mba\n"
    + "  scitex-orochi agent-restart head-mba --dry-run\n",
)
@click.argument("name")
@click.option("--dry-run", is_flag=True, help="Print commands without executing.")
def agent_restart(name: str, dry_run: bool) -> None:
    """Restart an agent: quit existing screen, then relaunch."""
    agent_dir = _resolve_agent_dir(name)
    if not agent_dir.is_dir():
        click.echo(f"Error: agent directory not found: {agent_dir}", err=True)
        sys.exit(1)

    cfg = _load_agent_config(name)
    host = cfg.get("host", "localhost")
    user = cfg.get("user", "")
    screen_name = cfg.get("screen_name", name)
    ssh = _ssh_prefix(host, user)

    # Stop if running
    try:
        if _screen_exists(screen_name, ssh):
            click.echo(f"Stopping {name}...")
            if not dry_run:
                _screen_quit(screen_name, ssh)
                time.sleep(2)
            else:
                click.echo(f"  [dry-run] Would quit screen '{screen_name}'")
        else:
            click.echo(f"{name} not currently running.")
    except subprocess.TimeoutExpired:
        click.echo(f"Warning: timeout checking screen on {host}", err=True)

    # Relaunch
    click.echo(f"\nRelaunching {name}...")
    ok = _launch_agent(name, dry_run=dry_run, force=False)
    if not ok:
        sys.exit(1)


@click.command(
    "agent-stop",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi agent-stop head-mba\n"
    + "  scitex-orochi agent-stop --all\n"
    + "  scitex-orochi agent-stop --all --force\n",
)
@click.argument("name", required=False)
@click.option("--all", "stop_all", is_flag=True, help="Stop all defined agents.")
@click.option("--force", is_flag=True, help="Ignore errors and continue.")
def agent_stop(name: str | None, stop_all: bool, force: bool) -> None:
    """Stop an agent's screen session, or all with --all."""
    if not stop_all and not name:
        click.echo("Error: provide an agent NAME or use --all.", err=True)
        sys.exit(2)

    if stop_all:
        agents = _list_agent_names()
        if not agents:
            click.echo("No agents found.", err=True)
            sys.exit(1)

        any_failure = False
        for agent_name in agents:
            ok = _stop_agent(agent_name, force=force)
            if not ok and not force:
                any_failure = True

        if any_failure and not force:
            sys.exit(1)
        return

    assert name is not None
    agent_dir = _resolve_agent_dir(name)
    if not agent_dir.is_dir():
        click.echo(f"Error: agent directory not found: {agent_dir}", err=True)
        sys.exit(1)

    ok = _stop_agent(name, force=force)
    if not ok and not force:
        sys.exit(1)


@click.command(
    "agent-status",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi agent-status\n"
    + "  scitex-orochi agent-status --json\n",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def agent_status(as_json: bool) -> None:
    """Show status of all defined agents (screen check + SSH health)."""
    agents = _list_agent_names()
    if not agents:
        if as_json:
            click.echo(json.dumps([], indent=2))
        else:
            click.echo(
                "No agents found in ~/.scitex/orochi/{shared,<host>}/agents/."
            )
        return

    rows = []
    for name in agents:
        rows.append(_agent_status_row(name))

    if as_json:
        click.echo(json.dumps(rows, indent=2))
        return

    # Table output
    click.echo(f"{'NAME':<35} {'HOST':<15} {'ROLE':<12} {'STATUS':<12}")
    click.echo("-" * 74)
    for r in rows:
        status = r["status"]
        if status == "running":
            color = "green"
        elif status == "stopped":
            color = "red"
        else:
            color = "yellow"
        click.echo(
            f"{r['name']:<35} {r['host']:<15} {r['role']:<12} "
            f"{click.style(status, fg=color):<21}"
        )

    running = sum(1 for r in rows if r["status"] == "running")
    click.echo(f"\n{len(rows)} agent(s) defined, {running} running")
