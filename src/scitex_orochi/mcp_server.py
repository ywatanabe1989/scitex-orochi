"""FastMCP Server for scitex-orochi."""

from __future__ import annotations

import json
import os
import platform

try:
    from fastmcp import FastMCP

    _FASTMCP_AVAILABLE = True
except ImportError:
    _FASTMCP_AVAILABLE = False


def _get_agent_name() -> str:
    return os.environ.get("SCITEX_OROCHI_AGENT") or os.environ.get(
        "OROCHI_AGENT", f"mcp-{platform.node()}"
    )


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
