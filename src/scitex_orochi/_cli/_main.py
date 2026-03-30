"""Orochi CLI -- Click-based command-line interface for agent communication."""

from __future__ import annotations

import asyncio
import json
import os
import platform
import sys

import click


def _get_agent_name() -> str:
    return os.environ.get("SCITEX_OROCHI_AGENT") or os.environ.get(
        "OROCHI_AGENT", platform.node()
    )


def _make_client(
    host: str, port: int, channels: list[str] | None = None
) -> "OrochiClient":
    from scitex_orochi._client import OrochiClient

    return OrochiClient(
        name=_get_agent_name(),
        host=host,
        port=port,
        channels=channels or ["#general"],
    )


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--host",
    default=None,
    envvar="SCITEX_OROCHI_HOST",
    help="Orochi server host [$SCITEX_OROCHI_HOST]",
)
@click.option(
    "--port",
    default=None,
    type=int,
    envvar="SCITEX_OROCHI_PORT",
    help="Orochi server port [$SCITEX_OROCHI_PORT]",
)
@click.pass_context
def orochi(ctx: click.Context, host: str | None, port: int | None) -> None:
    """Orochi -- Agent Communication Hub CLI."""
    from scitex_orochi._config import HOST, PORT

    ctx.ensure_object(dict)
    ctx.obj["host"] = host or HOST
    ctx.obj["port"] = port or PORT


@orochi.command()
@click.argument("channel")
@click.argument("message")
@click.pass_context
def send(ctx: click.Context, channel: str, message: str) -> None:
    """Send a message to a channel."""

    async def _run() -> None:
        async with _make_client(
            ctx.obj["host"], ctx.obj["port"], channels=[channel]
        ) as client:
            await client.send(channel, message)
            click.echo(f"Sent to {channel}: {message}")

    asyncio.run(_run())


@orochi.command()
@click.option(
    "--channel", default=None, help="Channel to listen on (default: #general)"
)
@click.pass_context
def listen(ctx: click.Context, channel: str | None) -> None:
    """Listen for messages (stream to stdout)."""
    ch = channel or "#general"

    async def _run() -> None:
        async with _make_client(
            ctx.obj["host"], ctx.obj["port"], channels=[ch]
        ) as client:
            click.echo(f"Listening on {ch} (Ctrl+C to stop)...", err=True)
            async for msg in client.listen():
                ch_name = msg.channel or "?"
                click.echo(f"[{msg.ts}] [{ch_name}] {msg.sender}: {msg.content}")

    asyncio.run(_run())


@orochi.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def who(ctx: click.Context, as_json: bool) -> None:
    """List connected agents."""

    async def _run() -> None:
        async with _make_client(ctx.obj["host"], ctx.obj["port"]) as client:
            agents = await client.who()
            if not agents:
                click.echo("No agents connected.")
                return
            if as_json:
                click.echo(json.dumps(agents, indent=2))
                return
            for agent_id, info in agents.items():
                if isinstance(info, dict):
                    status = info.get("status", "unknown")
                    channels = ", ".join(info.get("channels", []))
                    click.echo(f"  {agent_id}  status={status}  channels=[{channels}]")
                else:
                    click.echo(f"  {agent_id}: {info}")

    asyncio.run(_run())


@orochi.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def status(ctx: click.Context, as_json: bool) -> None:
    """Show server stats."""

    async def _run() -> None:
        async with _make_client(ctx.obj["host"], ctx.obj["port"]) as client:
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


@orochi.command()
@click.option(
    "--name",
    default=None,
    help="Agent name (default: $SCITEX_OROCHI_AGENT or hostname)",
)
@click.option(
    "--channels", default=None, help="Comma-separated channels (default: #general)"
)
@click.pass_context
def login(ctx: click.Context, name: str | None, channels: str | None) -> None:
    """Connect and stay online, streaming incoming messages."""
    ch_list = channels.split(",") if channels else ["#general"]

    async def _run() -> None:
        async with _make_client(
            ctx.obj["host"], ctx.obj["port"], channels=ch_list
        ) as client:
            click.echo(f"Logged in as {name or _get_agent_name()}")
            click.echo(f"Channels: {', '.join(ch_list)}")
            click.echo("Listening for messages... (Ctrl+C to quit)")
            async for msg in client.listen():
                ch = msg.channel or "?"
                click.echo(f"[{ch}] {msg.sender}: {msg.content}")

    asyncio.run(_run())


@orochi.command()
@click.argument("channel")
@click.pass_context
def join(ctx: click.Context, channel: str) -> None:
    """Join/subscribe to a channel."""

    async def _run() -> None:
        async with _make_client(ctx.obj["host"], ctx.obj["port"]) as client:
            await client.subscribe(channel)
            click.echo(f"Joined {channel}")

    asyncio.run(_run())


@orochi.command("channels")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def channels_cmd(ctx: click.Context, as_json: bool) -> None:
    """List all active channels."""

    async def _run() -> None:
        async with _make_client(ctx.obj["host"], ctx.obj["port"]) as client:
            agents = await client.who()
            ch_set: set[str] = set()
            for info in agents.values():
                if isinstance(info, dict):
                    ch_set.update(info.get("channels", []))
                elif isinstance(info, list):
                    ch_set.update(info)
            if not ch_set:
                click.echo("No active channels.")
                return
            if as_json:
                click.echo(json.dumps(sorted(ch_set), indent=2))
                return
            for ch in sorted(ch_set):
                click.echo(ch)

    asyncio.run(_run())


@orochi.command()
@click.option("--channel", default=None, help="Filter by channel")
@click.pass_context
def members(ctx: click.Context, channel: str | None) -> None:
    """List members of a channel (or all agents with their channels)."""

    async def _run() -> None:
        async with _make_client(ctx.obj["host"], ctx.obj["port"]) as client:
            agents = await client.who()
            if channel:
                for name, info in agents.items():
                    chs = (
                        info.get("channels", [])
                        if isinstance(info, dict)
                        else (info if isinstance(info, list) else [])
                    )
                    if channel in chs:
                        click.echo(name)
            else:
                for name, info in agents.items():
                    chs = (
                        info.get("channels", [])
                        if isinstance(info, dict)
                        else (info if isinstance(info, list) else [])
                    )
                    click.echo(f"{name}: {', '.join(chs)}")

    asyncio.run(_run())


@orochi.command()
@click.argument("channel")
@click.option("--limit", type=int, default=50, help="Max messages (default: 50)")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def history(ctx: click.Context, channel: str, limit: int, as_json: bool) -> None:
    """Show message history for a channel."""

    async def _run() -> None:
        async with _make_client(
            ctx.obj["host"], ctx.obj["port"], channels=[channel]
        ) as client:
            hist = await client.query_history(channel, limit=limit)
            if not hist:
                click.echo(f"No history for {channel}.")
                return
            if as_json:
                click.echo(json.dumps(hist, indent=2))
                return
            for entry in hist:
                ts = entry.get("ts", "?")
                sender = entry.get("sender", "?")
                content = entry.get("content", "")
                click.echo(f"[{ts}] {sender}: {content}")

    asyncio.run(_run())


@orochi.command()
@click.option(
    "--interval",
    type=int,
    default=0,
    help="Send heartbeat every N seconds (0 = once and exit)",
)
@click.option("--json", "as_json", is_flag=True, help="Print collected metrics as JSON")
@click.pass_context
def heartbeat(ctx: click.Context, interval: int, as_json: bool) -> None:
    """Send a heartbeat with system resource metrics."""
    from scitex_orochi._resources import collect_metrics

    async def _run() -> None:
        async with _make_client(ctx.obj["host"], ctx.obj["port"]) as client:
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


@orochi.command()
@click.pass_context
def serve(ctx: click.Context) -> None:
    """Start the Orochi hub server."""
    from scitex_orochi._server import main as server_main

    server_main()


def main() -> None:
    try:
        orochi(standalone_mode=True)
    except KeyboardInterrupt:
        pass
    except ConnectionRefusedError:
        from scitex_orochi._config import HOST, PORT

        click.echo(
            f"Error: Cannot connect to Orochi server at {HOST}:{PORT}",
            err=True,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
