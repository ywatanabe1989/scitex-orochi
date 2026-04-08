"""FastMCP Server for scitex-orochi."""

from __future__ import annotations

import json
import os
import platform
import sys

# ---------------------------------------------------------------------------
# Safety guards -- must run before any MCP setup
# ---------------------------------------------------------------------------

_TRUTHY = frozenset({"true", "1", "yes", "enable", "enabled"})


def _is_truthy(val: str | None) -> bool:
    return (val or "").lower() in _TRUTHY


def _guard_msg(msg: str) -> None:
    print(f"[scitex-orochi] {msg}", file=sys.stderr)


# 1. Generic disable switch
if _is_truthy(os.environ.get("SCITEX_OROCHI_DISABLE")):
    _guard_msg("Disabled via SCITEX_OROCHI_DISABLE")
    sys.exit(0)

# 2. Block telegram agent role
if (os.environ.get("CLAUDE_AGENT_ROLE") or "").lower() == "telegram":
    _guard_msg("BLOCKED: telegram agent must not run Orochi MCP server")
    sys.exit(1)

# 3. Block if Telegram bot token env vars are present
_telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get(
    "SCITEX_NOTIFICATION_TELEGRAM_BOT_TOKEN"
)
if _telegram_token:
    _guard_msg(
        "Telegram bot token detected -- Orochi MCP server refuses to run "
        "alongside Telegram bot"
    )
    sys.exit(1)

# ---------------------------------------------------------------------------

try:
    from fastmcp import FastMCP

    _FASTMCP_AVAILABLE = True
except ImportError:
    _FASTMCP_AVAILABLE = False


def _get_agent_name() -> str:
    return os.environ.get("SCITEX_OROCHI_AGENT", f"mcp-{platform.node()}")


def _make_client(channels: list[str] | None = None) -> "OrochiClient":
    from scitex_orochi._client import OrochiClient
    from scitex_orochi._config import HOST, PORT

    return OrochiClient(
        name=_get_agent_name(),
        host=HOST,
        port=PORT,
        channels=channels or ["#general"],
    )


if _FASTMCP_AVAILABLE:
    mcp = FastMCP("orochi-mcp", version="0.1.0")

    @mcp.tool()
    async def orochi_send(channel: str, message: str) -> str:
        """Send a message to an Orochi channel."""
        async with _make_client(channels=[channel]) as client:
            await client.send(channel, message)
        return json.dumps({"status": "sent", "channel": channel, "message": message})

    @mcp.tool()
    async def orochi_who() -> str:
        """List currently connected Orochi agents."""
        async with _make_client() as client:
            agents = await client.who()
        if not agents:
            return json.dumps({"agents": [], "count": 0})
        return json.dumps({"agents": agents, "count": len(agents)})

    @mcp.tool()
    async def orochi_history(channel: str = "#general", limit: int = 50) -> str:
        """Get message history for an Orochi channel."""
        async with _make_client(channels=[channel]) as client:
            history = await client.query_history(channel, limit=limit)
        return json.dumps(
            {"channel": channel, "messages": history, "count": len(history)}
        )

    @mcp.tool()
    async def orochi_channels() -> str:
        """List all active Orochi channels."""
        async with _make_client() as client:
            agents = await client.who()
        ch_set: set[str] = set()
        for info in agents.values():
            if isinstance(info, dict):
                ch_set.update(info.get("channels", []))
            elif isinstance(info, list):
                ch_set.update(info)
        return json.dumps({"channels": sorted(ch_set)})


def main() -> None:
    if not _FASTMCP_AVAILABLE:
        import sys

        print(
            "Error: fastmcp is required. Install with: pip install scitex-orochi[mcp]",
            file=sys.stderr,
        )
        sys.exit(1)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
