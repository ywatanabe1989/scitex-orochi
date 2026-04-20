"""scitex-orochi agent-restart command."""

from __future__ import annotations

import subprocess
import sys
import time

import click

from scitex_orochi._cli._helpers import EXAMPLES_HEADER

from ._helpers import (
    AGENTS_DIR,
    _load_agent_config,
    _screen_exists,
    _screen_quit,
    _ssh_prefix,
)
from ._lifecycle import _launch_agent


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
    agent_dir = AGENTS_DIR / name
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
