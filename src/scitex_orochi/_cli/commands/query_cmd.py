"""CLI commands: list-agents, show-status, list-channels, list-members, show-history."""

from __future__ import annotations

import asyncio
import json

import click

from scitex_orochi._cli._helpers import EXAMPLES_HEADER, make_client


# ── list-agents ─────────────────────────────────────────────────
@click.command(
    "list-agents",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi list-agents\n"
    + "  scitex-orochi list-agents --json\n",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def list_agents(ctx: click.Context, as_json: bool) -> None:
    """List connected agents."""

    async def _run() -> None:
        async with make_client(ctx.obj["host"], ctx.obj["port"]) as client:
            agents = await client.who()
            if as_json:
                click.echo(json.dumps(agents, indent=2))
                return
            if not agents:
                click.echo("No agents connected.")
                return
            for agent_id, info in agents.items():
                if isinstance(info, dict):
                    status = info.get("status", "unknown")
                    channels = ", ".join(info.get("channels", []))
                    click.echo(f"  {agent_id}  status={status}  channels=[{channels}]")
                else:
                    click.echo(f"  {agent_id}: {info}")

    asyncio.run(_run())


# ── show-status ─────────────────────────────────────────────────
@click.command(
    "show-status",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi show-status\n"
    + "  scitex-orochi show-status --json\n",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def show_status(ctx: click.Context, as_json: bool) -> None:
    """Show server stats."""

    async def _run() -> None:
        async with make_client(ctx.obj["host"], ctx.obj["port"]) as client:
            agents = await client.who()
            if as_json:
                click.echo(json.dumps({"agents": agents}, indent=2))
                return
            click.echo(f"Connected agents: {len(agents)}")
            for agent_id, info in agents.items():
                if isinstance(info, dict):
                    s = info.get("status", "unknown")
                    task = info.get("current_task", "")
                    line = f"  {agent_id}  [{s}]"
                    if task:
                        line += f"  task: {task}"
                    click.echo(line)
                else:
                    click.echo(f"  {agent_id}: {info}")

    asyncio.run(_run())


# ── list-channels ───────────────────────────────────────────────
@click.command(
    "list-channels",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi list-channels\n"
    + "  scitex-orochi list-channels --json\n",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def list_channels(ctx: click.Context, as_json: bool) -> None:
    """List all active channels."""

    async def _run() -> None:
        async with make_client(ctx.obj["host"], ctx.obj["port"]) as client:
            agents = await client.who()
            ch_set: set[str] = set()
            for info in agents.values():
                if isinstance(info, dict):
                    ch_set.update(info.get("channels", []))
                elif isinstance(info, list):
                    ch_set.update(info)
            if as_json:
                click.echo(json.dumps(sorted(ch_set), indent=2))
                return
            if not ch_set:
                click.echo("No active channels.")
                return
            for ch in sorted(ch_set):
                click.echo(ch)

    asyncio.run(_run())


# ── list-members ────────────────────────────────────────────────
@click.command(
    "list-members",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi list-members\n"
    + "  scitex-orochi list-members --channel '#general'\n"
    + "  scitex-orochi list-members --json\n",
)
@click.option("--channel", default=None, help="Filter by channel.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def list_members(ctx: click.Context, channel: str | None, as_json: bool) -> None:
    """List members of a channel (or all agents with their channels)."""

    async def _run() -> None:
        async with make_client(ctx.obj["host"], ctx.obj["port"]) as client:
            agents = await client.who()
            result: dict[str, list[str]] = {}
            for name, info in agents.items():
                chs = (
                    info.get("channels", [])
                    if isinstance(info, dict)
                    else (info if isinstance(info, list) else [])
                )
                if channel:
                    if channel in chs:
                        result[name] = chs
                else:
                    result[name] = chs

            if as_json:
                click.echo(json.dumps(result, indent=2))
                return
            if not result:
                if channel:
                    click.echo(f"No members in {channel}.")
                else:
                    click.echo("No agents connected.")
                return
            for name, chs in result.items():
                if channel:
                    click.echo(name)
                else:
                    click.echo(f"{name}: {', '.join(chs)}")

    asyncio.run(_run())


# ── show-history ────────────────────────────────────────────────
@click.command(
    "show-history",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi show-history '#general'\n"
    + "  scitex-orochi show-history --limit 20 '#general'\n"
    + "  scitex-orochi show-history --json '#general'\n",
)
@click.argument("channel")
@click.option("--limit", type=int, default=50, help="Max messages (default: 50).")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def show_history(ctx: click.Context, channel: str, limit: int, as_json: bool) -> None:
    """Show message history for a channel."""

    async def _run() -> None:
        async with make_client(
            ctx.obj["host"], ctx.obj["port"], channels=[channel]
        ) as client:
            hist = await client.query_history(channel, limit=limit)
            if as_json:
                click.echo(json.dumps(hist, indent=2))
                return
            if not hist:
                click.echo(f"No history for {channel}.")
                return
            for entry in hist:
                ts = entry.get("ts", "?")
                sender = entry.get("sender", "?")
                content = entry.get("content", "")
                click.echo(f"[{ts}] {sender}: {content}")

    asyncio.run(_run())
