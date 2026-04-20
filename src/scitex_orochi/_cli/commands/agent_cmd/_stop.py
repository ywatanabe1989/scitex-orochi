"""scitex-orochi agent-stop command."""

from __future__ import annotations

import sys

import click

from scitex_orochi._cli._helpers import EXAMPLES_HEADER

from ._helpers import AGENTS_DIR, _list_agent_names
from ._lifecycle import _stop_agent


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
    agent_dir = AGENTS_DIR / name
    if not agent_dir.is_dir():
        click.echo(f"Error: agent directory not found: {agent_dir}", err=True)
        sys.exit(1)

    ok = _stop_agent(name, force=force)
    if not ok and not force:
        sys.exit(1)
