"""CLI commands: send, listen, login, join."""

from __future__ import annotations

import asyncio
import json

import click

from scitex_orochi._cli._helpers import EXAMPLES_HEADER, make_client


# ── send ────────────────────────────────────────────────────────
@click.command(
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi send '#general' 'Build passed'\n"
    + "  scitex-orochi send --json '#alerts' 'Disk full'\n"
    + "  scitex-orochi send --dry-run '#general' 'test'\n"
)
@click.argument("channel")
@click.argument("message")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option(
    "--dry-run", is_flag=True, help="Show what would be sent without connecting."
)
@click.pass_context
def send(
    ctx: click.Context, channel: str, message: str, as_json: bool, dry_run: bool
) -> None:
    """Send a message to a channel."""
    if dry_run:
        result = {
            "action": "send",
            "channel": channel,
            "message": message,
            "host": ctx.obj["host"],
            "port": ctx.obj["port"],
        }
        if as_json:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(f"[dry-run] Would send to {channel}: {message}")
            click.echo(f"          Server: {ctx.obj['host']}:{ctx.obj['port']}")
        return

    async def _run() -> None:
        async with make_client(
            ctx.obj["host"], ctx.obj["port"], channels=[channel]
        ) as client:
            await client.send(channel, message)
            if as_json:
                click.echo(
                    json.dumps(
                        {"status": "sent", "channel": channel, "message": message}
                    )
                )
            else:
                click.echo(f"Sent to {channel}: {message}")

    asyncio.run(_run())


# ── listen ──────────────────────────────────────────────────────
@click.command(
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi listen --channel '#general'\n"
    + "  scitex-orochi listen --json --channel '#builds'\n"
)
@click.option(
    "--channel", default=None, help="Channel to listen on (default: #general)."
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output as JSONL (one JSON object per line).",
)
@click.pass_context
def listen(ctx: click.Context, channel: str | None, as_json: bool) -> None:
    """Listen for messages (stream to stdout)."""
    ch = channel or "#general"

    async def _run() -> None:
        async with make_client(
            ctx.obj["host"], ctx.obj["port"], channels=[ch]
        ) as client:
            if not as_json:
                click.echo(f"Listening on {ch} (Ctrl+C to stop)...", err=True)
            async for msg in client.listen():
                if as_json:
                    click.echo(
                        json.dumps(
                            {
                                "ts": msg.ts,
                                "channel": msg.channel or "?",
                                "sender": msg.sender,
                                "content": msg.content,
                            }
                        )
                    )
                else:
                    ch_name = msg.channel or "?"
                    click.echo(f"[{msg.ts}] [{ch_name}] {msg.sender}: {msg.content}")

    asyncio.run(_run())


# ── login ───────────────────────────────────────────────────────
@click.command(
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi login\n"
    + "  scitex-orochi login --name my-agent --channels '#general,#builds'\n"
    + "  scitex-orochi login --json\n"
)
@click.option(
    "--name",
    default=None,
    help="Agent name (default: $SCITEX_OROCHI_AGENT or hostname).",
)
@click.option(
    "--channels", default=None, help="Comma-separated channels (default: #general)."
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output as JSONL (one JSON object per line).",
)
@click.pass_context
def login(
    ctx: click.Context, name: str | None, channels: str | None, as_json: bool
) -> None:
    """Connect and stay online, streaming incoming messages."""
    from scitex_orochi._cli._helpers import get_agent_name

    ch_list = channels.split(",") if channels else ["#general"]

    async def _run() -> None:
        async with make_client(
            ctx.obj["host"], ctx.obj["port"], channels=ch_list
        ) as client:
            if not as_json:
                click.echo(f"Logged in as {name or get_agent_name()}")
                click.echo(f"Channels: {', '.join(ch_list)}")
                click.echo("Listening for messages... (Ctrl+C to quit)")
            async for msg in client.listen():
                if as_json:
                    click.echo(
                        json.dumps(
                            {
                                "channel": msg.channel or "?",
                                "sender": msg.sender,
                                "content": msg.content,
                            }
                        )
                    )
                else:
                    ch = msg.channel or "?"
                    click.echo(f"[{ch}] {msg.sender}: {msg.content}")

    asyncio.run(_run())


# ── join ────────────────────────────────────────────────────────
@click.command(
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi join '#alerts'\n"
    + "  scitex-orochi join --dry-run '#builds'\n"
    + "  scitex-orochi join --json '#general'\n"
)
@click.argument("channel")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option(
    "--dry-run", is_flag=True, help="Show what would happen without connecting."
)
@click.pass_context
def join(ctx: click.Context, channel: str, as_json: bool, dry_run: bool) -> None:
    """Join/subscribe to a channel."""
    if dry_run:
        result = {
            "action": "join",
            "channel": channel,
            "host": ctx.obj["host"],
            "port": ctx.obj["port"],
        }
        if as_json:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(f"[dry-run] Would join {channel}")
            click.echo(f"          Server: {ctx.obj['host']}:{ctx.obj['port']}")
        return

    async def _run() -> None:
        async with make_client(ctx.obj["host"], ctx.obj["port"]) as client:
            await client.subscribe(channel)
            if as_json:
                click.echo(json.dumps({"status": "joined", "channel": channel}))
            else:
                click.echo(f"Joined {channel}")

    asyncio.run(_run())
