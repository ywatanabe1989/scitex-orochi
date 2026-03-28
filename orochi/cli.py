"""Orochi CLI -- command-line interface for agent communication."""

from __future__ import annotations

import argparse
import asyncio
import os
import platform
import sys

from orochi.client import OrochiClient


def _get_agent_name() -> str:
    return os.environ.get("OROCHI_AGENT", platform.node())


def _get_host() -> str:
    return os.environ.get("OROCHI_HOST", "192.168.0.102")


def _get_port() -> int:
    return int(os.environ.get("OROCHI_PORT", "9559"))


def _make_client(channels: list[str] | None = None) -> OrochiClient:
    return OrochiClient(
        name=_get_agent_name(),
        host=_get_host(),
        port=_get_port(),
        channels=channels or ["#general"],
    )


async def cmd_send(args: argparse.Namespace) -> None:
    """Send a message to a channel."""
    async with _make_client(channels=[args.channel]) as client:
        await client.send(args.channel, args.message)
        print(f"Sent to {args.channel}: {args.message}")


async def cmd_listen(args: argparse.Namespace) -> None:
    """Listen for messages and stream to stdout."""
    channel = args.channel or "#general"
    async with _make_client(channels=[channel]) as client:
        print(f"Listening on {channel} (Ctrl+C to stop)...", file=sys.stderr)
        async for msg in client.listen():
            ch = msg.channel or "?"
            print(f"[{msg.ts}] [{ch}] {msg.sender}: {msg.content}", flush=True)


async def cmd_who(args: argparse.Namespace) -> None:
    """List connected agents."""
    async with _make_client() as client:
        agents = await client.who()
        if not agents:
            print("No agents connected.")
            return
        for agent_id, info in agents.items():
            if isinstance(info, dict):
                status = info.get("status", "unknown")
                channels = ", ".join(info.get("channels", []))
                print(f"  {agent_id}  status={status}  channels=[{channels}]")
            else:
                print(f"  {agent_id}: {info}")


async def cmd_status(args: argparse.Namespace) -> None:
    """Show server stats."""
    async with _make_client() as client:
        agents = await client.who()
        print(f"Connected agents: {len(agents)}")
        for agent_id, info in agents.items():
            if isinstance(info, dict):
                status = info.get("status", "unknown")
                task = info.get("current_task", "")
                line = f"  {agent_id}  [{status}]"
                if task:
                    line += f"  task: {task}"
                print(line)
            else:
                print(f"  {agent_id}: {info}")


async def cmd_login(args: argparse.Namespace) -> None:
    """Connect and stay online, streaming incoming messages like a chat client."""
    name = args.name or _get_agent_name()
    channels = args.channels.split(",") if args.channels else ["#general"]
    async with _make_client(channels=channels) as client:
        print(f"Logged in as {name}")
        print(f"Channels: {', '.join(channels)}")
        print("Listening for messages... (Ctrl+C to quit)")
        async for msg in client.listen():
            ch = msg.channel or "?"
            print(f"[{ch}] {msg.sender}: {msg.content}", flush=True)


async def cmd_join(args: argparse.Namespace) -> None:
    """Join/subscribe to a channel."""
    async with _make_client() as client:
        await client.subscribe(args.channel)
        print(f"Joined {args.channel}")


async def cmd_channels(args: argparse.Namespace) -> None:
    """List all active channels."""
    async with _make_client() as client:
        agents = await client.who()
        ch_set: set[str] = set()
        for info in agents.values():
            if isinstance(info, dict):
                ch_set.update(info.get("channels", []))
            elif isinstance(info, list):
                ch_set.update(info)
        if not ch_set:
            print("No active channels.")
            return
        for ch in sorted(ch_set):
            print(ch)


async def cmd_members(args: argparse.Namespace) -> None:
    """List members of a channel (or all agents with their channels)."""
    async with _make_client() as client:
        agents = await client.who()
        if args.channel:
            for name, info in agents.items():
                chs = (
                    info.get("channels", [])
                    if isinstance(info, dict)
                    else (info if isinstance(info, list) else [])
                )
                if args.channel in chs:
                    print(name)
        else:
            for name, info in agents.items():
                chs = (
                    info.get("channels", [])
                    if isinstance(info, dict)
                    else (info if isinstance(info, list) else [])
                )
                print(f"{name}: {', '.join(chs)}")


async def cmd_history(args: argparse.Namespace) -> None:
    """Show message history for a channel."""
    async with _make_client(channels=[args.channel]) as client:
        history = await client.query_history(args.channel, limit=args.limit)
        if not history:
            print(f"No history for {args.channel}.")
            return
        for entry in history:
            ts = entry.get("ts", "?")
            sender = entry.get("sender", "?")
            content = entry.get("content", "")
            print(f"[{ts}] {sender}: {content}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orochi",
        description="Orochi -- Agent Communication Hub CLI",
    )
    sub = parser.add_subparsers(dest="command")

    # send
    p_send = sub.add_parser("send", help="Send a message to a channel")
    p_send.add_argument("channel", help="Target channel (e.g. #general)")
    p_send.add_argument("message", help="Message content")

    # listen
    p_listen = sub.add_parser("listen", help="Listen for messages (stream to stdout)")
    p_listen.add_argument(
        "--channel", default=None, help="Channel to listen on (default: #general)"
    )

    # who
    sub.add_parser("who", help="List connected agents")

    # status
    sub.add_parser("status", help="Show server stats")

    # login
    p_login = sub.add_parser("login", help="Connect and stay online (like slack login)")
    p_login.add_argument(
        "--name", default=None, help="Agent name (default: $OROCHI_AGENT or hostname)"
    )
    p_login.add_argument(
        "--channels", default=None, help="Comma-separated channels (default: #general)"
    )

    # join
    p_join = sub.add_parser("join", help="Join/subscribe to a channel")
    p_join.add_argument("channel", help="Channel to join (e.g. #general)")

    # channels
    sub.add_parser("channels", help="List all active channels")

    # members
    p_members = sub.add_parser("members", help="List members of a channel (or all)")
    p_members.add_argument("--channel", default=None, help="Filter by channel")

    # history
    p_hist = sub.add_parser("history", help="Show message history for a channel")
    p_hist.add_argument("channel", help="Channel to query")
    p_hist.add_argument(
        "--limit", type=int, default=50, help="Max messages (default: 50)"
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    dispatch = {
        "send": cmd_send,
        "listen": cmd_listen,
        "who": cmd_who,
        "status": cmd_status,
        "history": cmd_history,
        "login": cmd_login,
        "join": cmd_join,
        "channels": cmd_channels,
        "members": cmd_members,
    }

    try:
        asyncio.run(dispatch[args.command](args))
    except KeyboardInterrupt:
        pass
    except ConnectionRefusedError:
        print(
            f"Error: Cannot connect to Orochi server at {_get_host()}:{_get_port()}",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
