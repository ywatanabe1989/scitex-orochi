"""Per-agent lifecycle operations: launch, stop, status row."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import click

from ._helpers import (
    AGENTS_DIR,
    DEV_CHANNEL_CONFIRM_DELAY,
    SETUP_SCRIPT,
    _is_local,
    _load_agent_config,
    _screen_exists,
    _screen_quit,
    _setup_workspace,
    _shell_quote,
    _ssh_prefix,
)


def _launch_agent(name: str, dry_run: bool = False, force: bool = False) -> bool:
    """Launch a single agent. Returns True on success."""
    agent_dir = AGENTS_DIR / name
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
    workspace = f"~/.scitex/orochi/workspaces/{name}"
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
