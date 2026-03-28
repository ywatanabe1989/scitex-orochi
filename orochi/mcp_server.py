"""Orochi MCP Server -- expose Orochi as tools for Claude Code via stdio JSON-RPC.

Implements the Model Context Protocol (MCP) using stdin/stdout JSON-RPC,
no external dependencies required beyond the orochi package itself.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import sys
from typing import Any

from orochi.client import OrochiClient


def _get_agent_name() -> str:
    return os.environ.get("OROCHI_AGENT", f"mcp-{platform.node()}")


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


# ── Tool definitions ──────────────────────────────────────────────

TOOLS = [
    {
        "name": "orochi_send",
        "description": "Send a message to an Orochi channel.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": "Target channel (e.g. #general)",
                },
                "message": {"type": "string", "description": "Message content"},
            },
            "required": ["channel", "message"],
        },
    },
    {
        "name": "orochi_listen",
        "description": "Get recent messages from an Orochi channel (returns history, not a live stream).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": "Channel to query (default: #general)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max messages to return (default: 10)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "orochi_who",
        "description": "List currently connected Orochi agents.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "orochi_history",
        "description": "Get message history for an Orochi channel.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel to query"},
                "limit": {
                    "type": "integer",
                    "description": "Max messages (default: 50)",
                },
            },
            "required": ["channel"],
        },
    },
]


# ── Tool implementations ─────────────────────────────────────────


async def tool_orochi_send(params: dict) -> str:
    channel = params["channel"]
    message = params["message"]
    async with _make_client(channels=[channel]) as client:
        await client.send(channel, message)
    return f"Sent to {channel}: {message}"


async def tool_orochi_listen(params: dict) -> str:
    channel = params.get("channel", "#general")
    limit = params.get("limit", 10)
    async with _make_client(channels=[channel]) as client:
        history = await client.query_history(channel, limit=limit)
    if not history:
        return f"No recent messages in {channel}."
    lines = []
    for entry in history:
        ts = entry.get("ts", "?")
        sender = entry.get("sender", "?")
        content = entry.get("content", "")
        lines.append(f"[{ts}] {sender}: {content}")
    return "\n".join(lines)


async def tool_orochi_who(params: dict) -> str:
    async with _make_client() as client:
        agents = await client.who()
    if not agents:
        return "No agents connected."
    lines = []
    for agent_id, info in agents.items():
        if isinstance(info, dict):
            status = info.get("status", "unknown")
            channels = ", ".join(info.get("channels", []))
            lines.append(f"{agent_id}  status={status}  channels=[{channels}]")
        else:
            lines.append(f"{agent_id}: {info}")
    return "\n".join(lines)


async def tool_orochi_history(params: dict) -> str:
    channel = params["channel"]
    limit = params.get("limit", 50)
    async with _make_client(channels=[channel]) as client:
        history = await client.query_history(channel, limit=limit)
    if not history:
        return f"No history for {channel}."
    lines = []
    for entry in history:
        ts = entry.get("ts", "?")
        sender = entry.get("sender", "?")
        content = entry.get("content", "")
        lines.append(f"[{ts}] {sender}: {content}")
    return "\n".join(lines)


TOOL_DISPATCH = {
    "orochi_send": tool_orochi_send,
    "orochi_listen": tool_orochi_listen,
    "orochi_who": tool_orochi_who,
    "orochi_history": tool_orochi_history,
}


# ── MCP stdio JSON-RPC protocol ──────────────────────────────────

SERVER_INFO = {
    "name": "orochi-mcp",
    "version": "0.1.0",
}

CAPABILITIES = {
    "tools": {},
}


def _jsonrpc_response(id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _jsonrpc_error(id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


async def handle_request(request: dict) -> dict | None:
    """Handle a single JSON-RPC request and return a response."""
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    # Notifications (no id) -- no response needed
    if req_id is None:
        return None

    if method == "initialize":
        return _jsonrpc_response(
            req_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": CAPABILITIES,
                "serverInfo": SERVER_INFO,
            },
        )

    elif method == "tools/list":
        return _jsonrpc_response(req_id, {"tools": TOOLS})

    elif method == "tools/call":
        tool_name = params.get("name", "")
        tool_params = params.get("arguments", {})
        handler = TOOL_DISPATCH.get(tool_name)
        if not handler:
            return _jsonrpc_error(req_id, -32601, f"Unknown tool: {tool_name}")
        try:
            result_text = await handler(tool_params)
            return _jsonrpc_response(
                req_id,
                {
                    "content": [{"type": "text", "text": result_text}],
                },
            )
        except Exception as e:
            return _jsonrpc_response(
                req_id,
                {
                    "content": [{"type": "text", "text": f"Error: {e}"}],
                    "isError": True,
                },
            )

    elif method == "ping":
        return _jsonrpc_response(req_id, {})

    else:
        return _jsonrpc_error(req_id, -32601, f"Method not found: {method}")


async def _run_stdio() -> None:
    """Main loop: read JSON-RPC from stdin, write responses to stdout."""
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin.buffer)

    w_transport, w_protocol = await asyncio.get_event_loop().connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout.buffer
    )
    writer = asyncio.StreamWriter(
        w_transport, w_protocol, None, asyncio.get_event_loop()
    )

    while True:
        line = await reader.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = await handle_request(request)
        if response is not None:
            out = json.dumps(response) + "\n"
            writer.write(out.encode())
            await writer.drain()


def main() -> None:
    try:
        asyncio.run(_run_stdio())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
