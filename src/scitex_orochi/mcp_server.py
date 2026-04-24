"""FastMCP Server for scitex-orochi."""

from __future__ import annotations

import json
import os
import platform
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scitex_orochi._client import OrochiClient

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
if (os.environ.get("SCITEX_OROCHI_AGENT_ROLE") or "").lower() == "telegram":
    _guard_msg("BLOCKED: telegram agent must not run Orochi MCP server")
    sys.exit(1)

# 3. Block if Telegram bot token env vars are present
_telegram_token = os.environ.get("SCITEX_OROCHI_TELEGRAM_BOT_TOKEN")
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
    async def orochi_history(
        channel: str = "#general",
        limit: int = 50,
        since: str = "",
        user: str = "",
        contains: str = "",
    ) -> str:
        """Get message history for an Orochi channel with optional filters.

        Args:
            channel: Channel name (e.g. #general)
            limit: Max messages to return
            since: ISO timestamp — only messages after this time
            user: Filter by sender name
            contains: Filter by substring in message text
        """
        async with _make_client(channels=[channel]) as client:
            history = await client.query_history(
                channel, since=since or None, limit=limit
            )
        # Client-side filters (hub may not support all server-side)
        if user:
            history = [m for m in history if m.get("sender", "") == user]
        if contains:
            history = [
                m
                for m in history
                if contains.lower() in (m.get("text", "") or "").lower()
            ]
        return json.dumps(
            {"channel": channel, "messages": history, "count": len(history)}
        )

    @mcp.tool()
    async def orochi_subscribe(
        channel: str,
        read: bool = True,
        write: bool = True,
    ) -> str:
        """Subscribe to an Orochi channel at runtime (no restart needed).

        The subscription is persisted server-side (ChannelMembership row),
        so it survives agent reboot. The two independent flags map to
        the lead msg#16884 bit-split:

        * ``read=True, write=True``  — full read-write (default)
        * ``read=True, write=False`` — listen only (no posts)
        * ``read=False, write=True`` — write-only digest target
          (post without pulling the firehose back — e.g. worker-progress
          → ``#ywatanabe``)

        Both flags default to True so existing call sites (``subscribe
        #chan``) keep the pre-split behaviour.
        """
        async with _make_client(channels=[channel] if read else []) as client:
            await client.subscribe(
                channel,
                can_read=bool(read),
                can_write=bool(write),
            )
        return json.dumps(
            {
                "status": "subscribed",
                "channel": channel,
                "can_read": bool(read),
                "can_write": bool(write),
            }
        )

    @mcp.tool()
    async def orochi_unsubscribe(channel: str) -> str:
        """Unsubscribe from an Orochi channel at runtime.

        Removes the persisted ChannelMembership row, so the agent will
        not auto-re-subscribe on reboot.
        """
        async with _make_client() as client:
            await client.unsubscribe(channel)
        return json.dumps({"status": "unsubscribed", "channel": channel})

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
    async def orochi_upload(
        file_path: str, channel: str = "#general", message: str = ""
    ) -> str:
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

        payload = json.dumps(
            {
                "data": b64,
                "filename": p.name,
                "mime_type": mime_type,
            }
        ).encode()
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            resp = await asyncio.get_event_loop().run_in_executor(
                None, urllib.request.urlopen, req
            )
            result = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return json.dumps(
                {"error": f"Upload failed ({e.code}): {e.read().decode()}"}
            )

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

        MAX_BYTES = 50 * 1024 * 1024  # 50 MB safety cap (prevent OOM on large media)
        try:
            resp = await asyncio.get_event_loop().run_in_executor(
                None, urllib.request.urlopen, dl_url
            )
            content_length = resp.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_BYTES:
                return json.dumps(
                    {
                        "error": f"File too large ({int(content_length) // 1024 // 1024}MB > 50MB limit)"
                    }
                )
            data = resp.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                return json.dumps({"error": "File too large (> 50MB limit)"})
        except urllib.error.HTTPError as e:
            return json.dumps({"error": f"Download failed ({e.code})"})

        dest = Path(save_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

        return json.dumps(
            {
                "status": "downloaded",
                "path": str(dest),
                "size": len(data),
            }
        )

    @mcp.tool()
    async def claude_account_status(agent: str = "") -> str:
        """Get Claude Code account status for local agent or fleet-wide.

        If agent is empty, reads local ~/.claude.json OAuth metadata.
        If agent is specified, queries hub for that agent's last-reported account state.

        Returns: email, org, billing_type, subscription status, usage_disabled_reason.
        """
        from pathlib import Path

        if not agent:
            # Local: read ~/.claude.json directly
            claude_json = Path.home() / ".claude.json"
            if not claude_json.exists():
                return json.dumps({"error": "~/.claude.json not found"})
            try:
                data = json.loads(claude_json.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                return json.dumps({"error": str(exc)})
            # Extract OAuth metadata (safe whitelist, no tokens)
            oauth = data.get("oauthAccount", {})
            return json.dumps(
                {
                    "email": oauth.get("emailAddress", ""),
                    "org_name": oauth.get("organizationName", ""),
                    "account_uuid": oauth.get("accountUuid", ""),
                    "display_name": oauth.get("displayName", ""),
                    "billing_type": oauth.get("billingType", ""),
                    "has_subscription": data.get("hasAvailableSubscription", None),
                    "usage_disabled_reason": data.get(
                        "cachedExtraUsageDisabledReason", ""
                    ),
                    "has_extra_usage": data.get("hasExtraUsageEnabled", None),
                    "source": "local",
                }
            )
        else:
            # Fleet: query hub registry for agent's account metadata
            import aiohttp

            hub = os.getenv("SCITEX_OROCHI_HUB_URL", "https://scitex-orochi.com")
            token = os.getenv("SCITEX_OROCHI_TOKEN", "")
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{hub}/api/agents/registry/",
                    params={"token": token},
                ) as resp:
                    if resp.status != 200:
                        return json.dumps({"error": f"hub returned {resp.status}"})
                    registry = await resp.json()
            # Find agent in registry
            for entry in registry if isinstance(registry, list) else []:
                if entry.get("name") == agent:
                    return json.dumps(
                        {
                            k: entry.get(k)
                            for k in [
                                "oauth_email",
                                "oauth_org_name",
                                "billing_type",
                                "has_available_subscription",
                                "usage_disabled_reason",
                                "has_extra_usage_enabled",
                            ]
                            if entry.get(k) is not None
                        }
                        | {"source": "hub", "agent": agent}
                    )
            return json.dumps({"error": f"agent '{agent}' not found in registry"})

    @mcp.tool()
    async def quota_status() -> str:
        """Get Claude Code quota/usage status for the local agent.

        Reads ~/.claude.json for subscription and usage state.
        Returns a summary indicating whether the agent can operate normally.
        """
        from pathlib import Path

        claude_json = Path.home() / ".claude.json"
        if not claude_json.exists():
            return json.dumps(
                {"status": "unknown", "reason": "~/.claude.json not found"}
            )
        try:
            data = json.loads(claude_json.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            return json.dumps({"status": "error", "reason": str(exc)})

        has_sub = data.get("hasAvailableSubscription", False)
        disabled_reason = data.get("cachedExtraUsageDisabledReason", "")
        has_extra = data.get("hasExtraUsageEnabled", False)

        # Determine operational status
        if disabled_reason == "out_of_credits":
            status = "quota_exhausted"
        elif not has_sub:
            status = "no_subscription"
        elif disabled_reason:
            status = "limited"
        else:
            status = "ok"

        return json.dumps(
            {
                "status": status,
                "has_subscription": has_sub,
                "usage_disabled_reason": disabled_reason or None,
                "has_extra_usage": has_extra,
                "agent": os.getenv("SCITEX_OROCHI_AGENT", "unknown"),
            }
        )

    @mcp.tool()
    async def fleet_report_tool(
        entity_type: str, entity_id: str, payload: str, source: str = ""
    ) -> str:
        """Report fleet entity state (machine/agent/server/session) to the hub."""
        import aiohttp

        hub = os.getenv("SCITEX_OROCHI_HUB_URL", "https://scitex-orochi.com")
        token = os.getenv("SCITEX_OROCHI_TOKEN", "")
        source = source or os.getenv("SCITEX_OROCHI_AGENT", "unknown")
        try:
            payload_obj = json.loads(payload) if isinstance(payload, str) else payload
        except json.JSONDecodeError:
            payload_obj = {"raw": payload}
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{hub}/api/fleet/report",
                json={
                    "token": token,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "payload": payload_obj,
                    "source": source,
                },
            ) as resp:
                return await resp.text()

    @mcp.tool()
    async def state_query(entity_type: str = "", since: str = "") -> str:
        """Query latest fleet state. Filter by entity_type (machine/agent/server/session) and since (ISO timestamp)."""
        import aiohttp

        hub = os.getenv("SCITEX_OROCHI_HUB_URL", "https://scitex-orochi.com")
        token = os.getenv("SCITEX_OROCHI_TOKEN", "")
        params: dict = {"token": token}
        if entity_type:
            params["entity_type"] = entity_type
        if since:
            params["since"] = since
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{hub}/api/fleet/state", params=params) as resp:
                return await resp.text()


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
