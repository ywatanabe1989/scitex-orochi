"""HTTP + Dashboard WebSocket server for Orochi."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp
import aiohttp.web as web

from scitex_orochi._auth import verify_token
from scitex_orochi._config import (
    CORS_ORIGINS,
    DASHBOARD_WS_UPSTREAM,
    MEDIA_MAX_SIZE,
    MEDIA_ROOT,
)

_CORS_SET = {o.strip() for o in CORS_ORIGINS.split(",") if o.strip()}
from scitex_orochi._media import MediaStore
from scitex_orochi._models import Message
from scitex_orochi._push import PushStore
from scitex_orochi._web_gitea import register_gitea_routes
from scitex_orochi._web_push import register_push_routes
from scitex_orochi._web_workspaces import register_workspace_routes

if TYPE_CHECKING:
    from scitex_orochi._server import OrochiServer

log = logging.getLogger("orochi.web")

DASHBOARD_DIR = Path(__file__).parent / "_dashboard"


async def handle_ws(request: web.Request) -> web.WebSocketResponse | web.Response:
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
                    try:
                        await server._handle_message(msg)
                    except Exception:
                        log.exception(
                            "Error routing dashboard message from %s to %s",
                            msg.sender,
                            msg.channel,
                        )

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


async def handle_resources(request: web.Request) -> web.Response:
    """GET /api/resources -- latest system resource metrics for all agents."""
    server: OrochiServer = request.app["orochi_server"]
    return web.json_response(server.get_resources_info())


async def handle_channels(request: web.Request) -> web.Response:
    """GET /api/channels -- list channels and members."""
    server: OrochiServer = request.app["orochi_server"]
    info = server.get_channels_info()
    # Include channels from store that have history but no current subscribers
    stored_channels = await server.store.distinct_channels()
    for ch in stored_channels:
        if ch not in info:
            info[ch] = []
    return web.json_response(info)


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


async def handle_post_message(request: web.Request) -> web.Response:
    """POST /api/messages -- send a message via REST.

    Primary send path for the dashboard UI.  Cloudflare tunnels reliably
    pass HTTP but may silently drop WebSocket client-to-server frames,
    so the dashboard always uses this REST endpoint instead of WS.
    """
    token = request.query.get("token")
    if not verify_token(token):
        return web.json_response({"error": "Unauthorized"}, status=401)

    server: OrochiServer = request.app["orochi_server"]
    body = await request.json()
    sender = body.get("sender", "user")
    payload = body.get("payload", {})
    if not payload.get("channel"):
        return web.json_response({"error": "payload.channel is required"}, status=400)

    msg = Message(
        type="message",
        sender=sender,
        payload=payload,
    )
    try:
        await server._handle_message(msg)
    except Exception:
        log.exception(
            "Error routing REST message from %s to %s", sender, payload.get("channel")
        )
        return web.json_response({"error": "internal routing error"}, status=500)
    return web.json_response({"status": "ok", "id": msg.id}, status=201)


async def handle_config(request: web.Request) -> web.Response:
    """GET /api/config -- dashboard configuration."""
    return web.json_response({"ws_upstream": DASHBOARD_WS_UPSTREAM or ""})


async def handle_stats(request: web.Request) -> web.Response:
    """GET /api/stats -- server statistics."""
    server: OrochiServer = request.app["orochi_server"]
    tg = server.telegram_bridge
    push_store: PushStore | None = request.app.get("push_store")
    push_subscriptions = 0
    if push_store:
        push_subscriptions = await push_store.subscription_count()
    all_channels = await server.get_all_channel_names()
    return web.json_response(
        {
            "agents_online": len(server.agents),
            "channels_active": len(server.channels),
            "observers_connected": len(server._observers),
            "agents": [a.name for a in server.agents.values()],
            "channels": all_channels,
            "telegram_bridge": {
                "enabled": tg is not None,
                "running": tg._running if tg else False,
            },
            "push_subscriptions": push_subscriptions,
        }
    )


async def handle_upload(request: web.Request) -> web.Response:
    """POST /api/upload -- multipart file upload."""
    token = request.query.get("token")
    if not verify_token(token):
        return web.json_response({"error": "Unauthorized"}, status=401)

    reader = await request.multipart()
    field = await reader.next()
    if field is None:
        return web.json_response({"error": "No file field"}, status=400)
    if not isinstance(field, aiohttp.BodyPartReader):
        return web.json_response({"error": "No file field"}, status=400)
    if field.name != "file":
        return web.json_response({"error": "No file field"}, status=400)

    data = await field.read(decode=False)
    filename = field.filename or "upload"
    mime_type = field.headers.get("Content-Type", "") if field.headers else ""

    media = MediaStore()
    try:
        result = media.save(data, filename, mime_type)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=413)

    return web.json_response(result, status=201)


async def handle_upload_base64(request: web.Request) -> web.Response:
    """POST /api/upload-base64 -- base64-encoded file upload."""
    token = request.query.get("token")
    if not verify_token(token):
        return web.json_response({"error": "Unauthorized"}, status=401)

    body = await request.json()
    b64_data = body.get("data", "")
    filename = body.get("filename", "upload")
    mime_type = body.get("mime_type", "")

    if not b64_data:
        return web.json_response({"error": "No data field"}, status=400)

    try:
        data = base64.b64decode(b64_data)
    except Exception:
        return web.json_response({"error": "Invalid base64"}, status=400)

    media = MediaStore()
    try:
        result = media.save(data, filename, mime_type)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=413)

    return web.json_response(result, status=201)


async def handle_index(request: web.Request) -> web.Response | web.FileResponse:
    """Serve the dashboard index.html."""
    index_path = DASHBOARD_DIR / "index.html"
    if index_path.exists():
        return web.FileResponse(index_path)
    return web.Response(
        status=200,
        text="Orochi Dashboard -- static files not yet deployed.",
        content_type="text/plain",
    )


async def handle_service_worker(
    request: web.Request,
) -> web.Response | web.FileResponse:
    """Serve sw.js from root scope for PWA support."""
    sw_path = DASHBOARD_DIR / "sw.js"
    if sw_path.exists():
        return web.FileResponse(
            sw_path, headers={"Content-Type": "application/javascript"}
        )
    return web.Response(status=404, text="Service worker not found")


@web.middleware
async def no_cache_static(request: web.Request, handler):
    """Set Cache-Control headers on static assets to prevent Cloudflare caching."""
    resp = await handler(request)
    if request.path.startswith(("/static", "/media")):
        try:
            resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        except (RuntimeError, TypeError):
            pass  # Skip if headers are frozen (e.g. WebSocketResponse)
    return resp


async def _init_push_store(app: web.Application) -> None:
    """Initialize PushStore on app startup and register push message hook."""
    server: OrochiServer = app["orochi_server"]
    # Use the same DB path as the message store for co-location
    db_path = server.store.db_path
    push_store = PushStore(db_path)
    await push_store.open()
    app["push_store"] = push_store

    # Register push notification hook on the server
    from scitex_orochi._push_hook import create_push_hook

    hook = create_push_hook(push_store)
    server._message_hooks.append(hook)
    log.info("Push notification store initialized with message hook")


async def _cleanup_push_store(app: web.Application) -> None:
    """Close PushStore on app shutdown."""
    push_store: PushStore | None = app.get("push_store")
    if push_store:
        await push_store.close()


@web.middleware
async def cors_middleware(request: web.Request, handler):
    """Add CORS headers for configured origins (SCITEX_OROCHI_CORS_ORIGINS)."""
    origin = request.headers.get("Origin", "")
    if request.method == "OPTIONS" and origin in _CORS_SET:
        return web.Response(
            status=204,
            headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Max-Age": "86400",
            },
        )
    resp = await handler(request)
    if origin in _CORS_SET:
        resp.headers["Access-Control-Allow-Origin"] = origin
    return resp


def create_web_app(server: OrochiServer) -> web.Application:
    """Create the aiohttp application with routes."""
    middlewares = [no_cache_static]
    if _CORS_SET:
        middlewares.append(cors_middleware)

    app = web.Application(client_max_size=MEDIA_MAX_SIZE, middlewares=middlewares)
    app["orochi_server"] = server

    # Lifecycle hooks for push store
    app.on_startup.append(_init_push_store)
    app.on_cleanup.append(_cleanup_push_store)

    # WebSocket for dashboard
    app.router.add_get("/ws", handle_ws)

    # REST API
    app.router.add_get("/api/agents", handle_agents)
    app.router.add_get("/api/resources", handle_resources)
    app.router.add_get("/api/channels", handle_channels)
    app.router.add_get("/api/messages", handle_messages)
    app.router.add_post("/api/messages", handle_post_message)
    app.router.add_get("/api/history/{channel}", handle_history)
    app.router.add_get("/api/config", handle_config)
    app.router.add_get("/api/stats", handle_stats)

    # Modular route groups
    register_workspace_routes(app)
    register_gitea_routes(app)
    register_push_routes(app)

    # Media upload/serve
    app.router.add_post("/api/upload", handle_upload)
    app.router.add_post("/api/upload-base64", handle_upload_base64)
    media_path = Path(MEDIA_ROOT)
    try:
        media_path.mkdir(parents=True, exist_ok=True)
        app.router.add_static("/media", media_path, show_index=False)
    except OSError:
        log.warning("Cannot create MEDIA_ROOT=%s; /media serving disabled", MEDIA_ROOT)

    # PWA service worker (must be at root scope)
    app.router.add_get("/sw.js", handle_service_worker)

    # Static files (dashboard UI)
    if DASHBOARD_DIR.exists():
        app.router.add_get("/", handle_index)
        app.router.add_static("/static", DASHBOARD_DIR / "static", show_index=False)
    else:
        app.router.add_get("/", handle_index)

    return app
