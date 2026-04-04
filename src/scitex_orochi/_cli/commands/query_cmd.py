"""CLI commands: who, status, channels, members, history, heartbeat."""

from __future__ import annotations

import asyncio
import json

import click

from scitex_orochi._cli._helpers import EXAMPLES_HEADER, make_client


# ── who ─────────────────────────────────────────────────────────
@click.command(
    epilog=EXAMPLES_HEADER + "  scitex-orochi who\n" + "  scitex-orochi who --json\n",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def who(ctx: click.Context, as_json: bool) -> None:
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


# ── status ──────────────────────────────────────────────────────
@click.command(
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi status\n"
    + "  scitex-orochi status --json\n",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def status(ctx: click.Context, as_json: bool) -> None:
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


# ── channels ────────────────────────────────────────────────────
@click.command(
    "channels",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi channels\n"
    + "  scitex-orochi channels --json\n",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def channels_cmd(ctx: click.Context, as_json: bool) -> None:
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


# ── members ─────────────────────────────────────────────────────
@click.command(
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi members\n"
    + "  scitex-orochi members --channel '#general'\n"
    + "  scitex-orochi members --json\n",
)
@click.option("--channel", default=None, help="Filter by channel.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def members(ctx: click.Context, channel: str | None, as_json: bool) -> None:
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


# ── history ─────────────────────────────────────────────────────
@click.command(
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi history '#general'\n"
    + "  scitex-orochi history --limit 20 '#general'\n"
    + "  scitex-orochi history --json '#general'\n",
)
@click.argument("channel")
@click.option("--limit", type=int, default=50, help="Max messages (default: 50).")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def history(ctx: click.Context, channel: str, limit: int, as_json: bool) -> None:
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


# ── heartbeat ───────────────────────────────────────────────────
@click.command(
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi heartbeat\n"
    + "  scitex-orochi heartbeat --interval 30\n"
    + "  scitex-orochi heartbeat --json\n",
)
@click.option(
    "--interval", type=int, default=0, help="Repeat every N seconds (0 = once)."
)
@click.option("--json", "as_json", is_flag=True, help="Output metrics as JSON.")
@click.pass_context
def heartbeat(ctx: click.Context, interval: int, as_json: bool) -> None:
    """Send a heartbeat with system resource metrics."""
    from scitex_orochi._resources import collect_metrics

    async def _run() -> None:
        async with make_client(ctx.obj["host"], ctx.obj["port"]) as client:
            while True:
                metrics = collect_metrics()
                await client.heartbeat(resources=metrics)
                if as_json:
                    click.echo(json.dumps(metrics, indent=2))
                else:
                    click.echo(
                        f"Heartbeat sent: "
                        f"load={metrics.get('load_avg_1m', '?')} "
                        f"mem={metrics.get('mem_used_percent', '?')}% "
                        f"disk={metrics.get('disk_used_percent', '?')}%"
                    )
                if interval <= 0:
                    break
                await asyncio.sleep(interval)

    asyncio.run(_run())
