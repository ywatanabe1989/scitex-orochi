"""scitex-orochi agent-status command."""

from __future__ import annotations

import json

import click

from scitex_orochi._cli._helpers import EXAMPLES_HEADER

from ._helpers import _list_agent_names
from ._lifecycle import _agent_status_row


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
            click.echo("No agents found in ~/.scitex/orochi/agents/")
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
