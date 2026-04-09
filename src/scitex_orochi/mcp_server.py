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

    @mcp.tool()
    async def orochi_machine_status() -> str:
        """Report the local machine's resource, version, process, and git status.

        Uses scitex_orochi._status.get_machine_status() if available.
        Safe to call from any agent; returns stdlib-collected data only.
        """
        try:
            from scitex_orochi._status import get_machine_status

            status = get_machine_status()
            return json.dumps(status)
        except Exception as e:
            return json.dumps({"error": f"status unavailable: {e}"})

    @mcp.tool()
    async def orochi_upload(file_path: str, channel: str = "#general", message: str = "") -> str:
        """Upload a file to Orochi and optionally share it in a channel.

        Args:
            file_path: Absolute path to the file to upload.
            channel: Channel to share the file in (default: #general).
            message: Optional message to accompany the file.
        """
        import base64
        import mimetypes
        from pathlib import Path

        from scitex_orochi._config import DASHBOARD_PORT, HOST, OROCHI_TOKEN

        p = Path(file_path)
        if not p.exists():
            return json.dumps({"error": f"File not found: {file_path}"})
        if not p.is_file():
            return json.dumps({"error": f"Not a file: {file_path}"})

        data = p.read_bytes()
        mime_type = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        b64 = base64.b64encode(data).decode()

        url = f"http://{HOST}:{DASHBOARD_PORT}/api/upload-base64"
        headers = {"Content-Type": "application/json"}
        if OROCHI_TOKEN:
            url += f"?token={OROCHI_TOKEN}"

        import asyncio
        import urllib.request

        payload = json.dumps({
            "data": b64,
            "filename": p.name,
            "mime_type": mime_type,
        }).encode()
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            resp = await asyncio.get_event_loop().run_in_executor(
                None, urllib.request.urlopen, req
            )
            result = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return json.dumps({"error": f"Upload failed ({e.code}): {e.read().decode()}"})

        # Share in channel if requested
        if channel:
            attach_msg = message or f"Shared file: {p.name}"
            metadata = {"attachments": [result]}
            async with _make_client(channels=[channel]) as client:
                await client.send(channel, attach_msg, metadata=metadata)

        return json.dumps({"status": "uploaded", **result})

    @mcp.tool()
    async def orochi_download(url: str, save_path: str) -> str:
        """Download a file from Orochi media.

        Args:
            url: The file URL (from a message attachment).
            save_path: Local path to save the downloaded file.
        """
        from pathlib import Path

        from scitex_orochi._config import DASHBOARD_PORT, HOST, OROCHI_TOKEN

        # Resolve relative media URLs to full URLs
        if url.startswith("/media/") or url.startswith("media/"):
            url = f"http://{HOST}:{DASHBOARD_PORT}/{url.lstrip('/')}"

        import asyncio
        import urllib.request

        dl_url = url
        if OROCHI_TOKEN and "?" in dl_url:
            dl_url += f"&token={OROCHI_TOKEN}"
        elif OROCHI_TOKEN:
            dl_url += f"?token={OROCHI_TOKEN}"

        try:
            resp = await asyncio.get_event_loop().run_in_executor(
                None, urllib.request.urlopen, dl_url
            )
            data = resp.read()
        except urllib.error.HTTPError as e:
            return json.dumps({"error": f"Download failed ({e.code})"})

        dest = Path(save_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

        return json.dumps({
            "status": "downloaded",
            "path": str(dest),
            "size": len(data),
        })


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
