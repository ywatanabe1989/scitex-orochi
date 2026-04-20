"""scitex-orochi agent-launch command."""

from __future__ import annotations

import sys

import click

from scitex_orochi._cli._helpers import EXAMPLES_HEADER

from ._helpers import _list_agent_names
from ._lifecycle import _launch_agent


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

    Reads agent definition from ~/.scitex/orochi/agents/<name>/,
    sets up the workspace, and starts a screen session with claude.
    """
    if not launch_all and not name:
        click.echo("Error: provide an agent NAME or use --all.", err=True)
        sys.exit(2)

    if launch_all:
        agents = _list_agent_names()
        if not agents:
            click.echo("No agents found in ~/.scitex/orochi/agents/", err=True)
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
