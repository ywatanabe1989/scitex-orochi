"""HTTP + Dashboard WebSocket server for Orochi."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp
import aiohttp.web as web

from scitex_orochi._auth import verify_token
from scitex_orochi._models import Message

if TYPE_CHECKING:
    from scitex_orochi._server import OrochiServer

log = logging.getLogger("orochi.web")

DASHBOARD_DIR = Path(__file__).parent / "_dashboard"


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


async def handle_messages(request: web.Request) -> web.Response:
    """GET /api/messages?limit=100 -- recent messages across all channels."""
    server: OrochiServer = request.app["orochi_server"]
    limit = int(request.query.get("limit", "100"))
    limit = min(limit, 500)  # cap at 500
    rows = await server.store.recent(limit=limit)
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


async def handle_gitea_list_issues(request: web.Request) -> web.Response:
    """GET /api/gitea/issues/{owner}/{repo} -- list issues."""
    server: OrochiServer = request.app["orochi_server"]
    owner = request.match_info["owner"]
    repo = request.match_info["repo"]
    state = request.query.get("state", "open")
    try:
        issues = await server.gitea.list_issues(owner, repo, state=state)
        return web.json_response(issues)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=502)


async def handle_gitea_create_issue(request: web.Request) -> web.Response:
    """POST /api/gitea/issues/{owner}/{repo} -- create an issue."""
    server: OrochiServer = request.app["orochi_server"]
    owner = request.match_info["owner"]
    repo = request.match_info["repo"]
    body = await request.json()
    title = body.get("title", "")
    if not title:
        return web.json_response({"error": "title is required"}, status=400)
    try:
        issue = await server.gitea.create_issue(
            owner=owner,
            repo=repo,
            title=title,
            body=body.get("body", ""),
            labels=body.get("labels"),
        )
        return web.json_response(issue, status=201)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=502)


async def handle_gitea_list_repos(request: web.Request) -> web.Response:
    """GET /api/gitea/repos -- list repositories."""
    server: OrochiServer = request.app["orochi_server"]
    org = request.query.get("org", "")
    try:
        repos = await server.gitea.list_repos(org=org)
        return web.json_response(repos)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=502)


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
    app.router.add_get("/api/messages", handle_messages)
    app.router.add_get("/api/history/{channel}", handle_history)
    app.router.add_get("/api/stats", handle_stats)

    # Static files (dashboard UI)
    if DASHBOARD_DIR.exists():
        app.router.add_get("/", handle_index)
        app.router.add_static("/static", DASHBOARD_DIR / "static", show_index=False)
    else:
        app.router.add_get("/", handle_index)

    return app
