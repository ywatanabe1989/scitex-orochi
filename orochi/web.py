"""HTTP + Dashboard WebSocket server for Orochi."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp
import aiohttp.web as web

from orochi.auth import verify_token
from orochi.models import Message

if TYPE_CHECKING:
    from orochi.server import OrochiServer

log = logging.getLogger("orochi.web")

DASHBOARD_DIR = Path(__file__).parent / "dashboard"


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    """WebSocket endpoint for dashboard observer connections."""
    server: OrochiServer = request.app["orochi_server"]

    # Auth check from query string
    token = request.query.get("token")
    if not verify_token(token):
        return web.Response(status=401, text="Unauthorized")

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    server.add_observer(ws)
    try:
        async for ws_msg in ws:
            if ws_msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(ws_msg.data)
                except json.JSONDecodeError:
                    continue

                # Dashboard can send messages as "user"
                if data.get("type") == "message":
                    msg = Message(
                        type="message",
                        sender=data.get("sender", "user"),
                        payload=data.get("payload", {}),
                    )
                    await server._handle_message(msg)

            elif ws_msg.type in (
                aiohttp.WSMsgType.ERROR,
                aiohttp.WSMsgType.CLOSE,
            ):
                break
    finally:
        server.remove_observer(ws)

    return ws


async def handle_agents(request: web.Request) -> web.Response:
    """GET /api/agents -- list all connected agents."""
    server: OrochiServer = request.app["orochi_server"]
    return web.json_response(server.get_agents_info())


async def handle_channels(request: web.Request) -> web.Response:
    """GET /api/channels -- list channels and members."""
    server: OrochiServer = request.app["orochi_server"]
    return web.json_response(server.get_channels_info())


async def handle_history(request: web.Request) -> web.Response:
    """GET /api/history/{channel} -- message history for a channel."""
    server: OrochiServer = request.app["orochi_server"]
    channel = request.match_info["channel"]
    # Channel names in URLs use the name without # prefix
    if not channel.startswith("#"):
        channel = f"#{channel}"
    since = request.query.get("since")
    limit = int(request.query.get("limit", "50"))
    rows = await server.store.query(channel=channel, since=since, limit=limit)
    return web.json_response(rows)


async def handle_stats(request: web.Request) -> web.Response:
    """GET /api/stats -- server statistics."""
    server: OrochiServer = request.app["orochi_server"]
    return web.json_response(
        {
            "agents_online": len(server.agents),
            "channels_active": len(server.channels),
            "observers_connected": len(server._observers),
            "agents": [a.name for a in server.agents.values()],
            "channels": list(server.channels.keys()),
        }
    )


async def handle_index(request: web.Request) -> web.Response:
    """Serve the dashboard index.html."""
    index_path = DASHBOARD_DIR / "index.html"
    if index_path.exists():
        return web.FileResponse(index_path)
    return web.Response(
        status=200,
        text="Orochi Dashboard -- static files not yet deployed.",
        content_type="text/plain",
    )


def create_web_app(server: OrochiServer) -> web.Application:
    """Create the aiohttp application with routes."""

    app = web.Application()
    app["orochi_server"] = server

    # WebSocket for dashboard
    app.router.add_get("/ws", handle_ws)

    # REST API
    app.router.add_get("/api/agents", handle_agents)
    app.router.add_get("/api/channels", handle_channels)
    app.router.add_get("/api/history/{channel}", handle_history)
    app.router.add_get("/api/stats", handle_stats)

    # Static files (dashboard UI)
    if DASHBOARD_DIR.exists():
        app.router.add_get("/", handle_index)
        app.router.add_static("/static", DASHBOARD_DIR / "static", show_index=False)
    else:
        app.router.add_get("/", handle_index)

    return app
