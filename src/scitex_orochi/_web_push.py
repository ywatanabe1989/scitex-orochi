"""Push notification API routes for Orochi dashboard PWA."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import aiohttp.web as web

from scitex_orochi._auth import verify_token
from scitex_orochi._push import PushStore, get_vapid_keys_path, load_vapid_keys

if TYPE_CHECKING:
    pass

log = logging.getLogger("orochi.web.push")


async def handle_vapid_key(request: web.Request) -> web.Response:
    """GET /api/push/vapid-key -- return public VAPID key for client."""
    push_store: PushStore | None = request.app.get("push_store")
    if push_store is None:
        return web.json_response(
            {"error": "Push notifications not configured"}, status=503
        )

    keys = load_vapid_keys(get_vapid_keys_path())
    if keys is None:
        return web.json_response(
            {"error": "VAPID keys not generated. Run: scitex-orochi vapid-generate"},
            status=503,
        )

    return web.json_response({"public_key": keys["public_key"]})


async def handle_push_subscribe(request: web.Request) -> web.Response:
    """POST /api/push/subscribe -- store a push subscription."""
    token = request.query.get("token")
    if not verify_token(token):
        return web.json_response({"error": "Unauthorized"}, status=401)

    push_store: PushStore | None = request.app.get("push_store")
    if push_store is None:
        return web.json_response(
            {"error": "Push notifications not configured"}, status=503
        )

    body = await request.json()
    endpoint = body.get("endpoint", "").strip()
    keys = body.get("keys", {})
    p256dh = keys.get("p256dh", "").strip()
    auth = keys.get("auth", "").strip()

    if not endpoint or not p256dh or not auth:
        return web.json_response(
            {"error": "endpoint, keys.p256dh, and keys.auth are required"},
            status=400,
        )

    user_agent = request.headers.get("User-Agent", "")

    await push_store.add_subscription(
        endpoint=endpoint,
        keys_p256dh=p256dh,
        keys_auth=auth,
        user_agent=user_agent,
    )

    count = await push_store.subscription_count()
    return web.json_response(
        {"status": "subscribed", "total_subscriptions": count}, status=201
    )


async def handle_push_unsubscribe(request: web.Request) -> web.Response:
    """POST /api/push/unsubscribe -- remove a push subscription."""
    token = request.query.get("token")
    if not verify_token(token):
        return web.json_response({"error": "Unauthorized"}, status=401)

    push_store: PushStore | None = request.app.get("push_store")
    if push_store is None:
        return web.json_response(
            {"error": "Push notifications not configured"}, status=503
        )

    body = await request.json()
    endpoint = body.get("endpoint", "").strip()
    if not endpoint:
        return web.json_response({"error": "endpoint is required"}, status=400)

    removed = await push_store.remove_subscription(endpoint)
    return web.json_response({"status": "unsubscribed", "was_subscribed": removed})


def register_push_routes(app: web.Application) -> None:
    """Register push notification routes on the app."""
    app.router.add_get("/api/push/vapid-key", handle_vapid_key)
    app.router.add_post("/api/push/subscribe", handle_push_subscribe)
    app.router.add_post("/api/push/unsubscribe", handle_push_unsubscribe)
