"""Workspace CRUD routes for Orochi dashboard."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import aiohttp.web as web

from scitex_orochi._auth import verify_token

if TYPE_CHECKING:
    from scitex_orochi._server import OrochiServer

log = logging.getLogger("orochi.web.workspaces")


async def handle_workspaces(request: web.Request) -> web.Response:
    """GET /api/workspaces -- list all workspaces."""
    server: OrochiServer = request.app["orochi_server"]
    if not server.workspaces:
        return web.json_response([])
    workspaces = await server.workspaces.list_workspaces()
    return web.json_response([ws.to_dict() for ws in workspaces])


async def handle_workspace(request: web.Request) -> web.Response:
    """GET /api/workspaces/{id} -- get a workspace."""
    server: OrochiServer = request.app["orochi_server"]
    ws_id = request.match_info["id"]
    if not server.workspaces:
        return web.json_response({"error": "Workspaces not initialized"}, status=503)
    ws = await server.workspaces.get_workspace(ws_id)
    if not ws:
        return web.json_response({"error": "Not found"}, status=404)
    return web.json_response(ws.to_dict())


async def handle_create_workspace(request: web.Request) -> web.Response:
    """POST /api/workspaces -- create a workspace."""
    token = request.query.get("token")
    if not await verify_token(token):
        return web.json_response({"error": "Unauthorized"}, status=401)
    server: OrochiServer = request.app["orochi_server"]
    if not server.workspaces:
        return web.json_response({"error": "Workspaces not initialized"}, status=503)
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        return web.json_response({"error": "name is required"}, status=400)
    try:
        ws = await server.workspaces.create_workspace(
            name=name,
            description=body.get("description", ""),
            channels=body.get("channels"),
        )
        # Auto-generate a workspace token
        wt = await server.workspaces.create_workspace_token(ws.id, label="default")
        result = ws.to_dict()
        result["token"] = wt["token"]
        return web.json_response(result, status=201)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def handle_delete_workspace(request: web.Request) -> web.Response:
    """DELETE /api/workspaces/{id} -- delete a workspace."""
    token = request.query.get("token")
    if not await verify_token(token):
        return web.json_response({"error": "Unauthorized"}, status=401)
    server: OrochiServer = request.app["orochi_server"]
    ws_id = request.match_info["id"]
    if not server.workspaces:
        return web.json_response({"error": "Workspaces not initialized"}, status=503)
    deleted = await server.workspaces.delete_workspace(ws_id)
    if not deleted:
        return web.json_response(
            {"error": "Cannot delete (not found or default)"}, status=400
        )
    return web.json_response({"ok": True})


async def handle_workspace_channels(request: web.Request) -> web.Response:
    """POST /api/workspaces/{id}/channels -- add a channel to workspace."""
    token = request.query.get("token")
    if not await verify_token(token):
        return web.json_response({"error": "Unauthorized"}, status=401)
    server: OrochiServer = request.app["orochi_server"]
    ws_id = request.match_info["id"]
    if not server.workspaces:
        return web.json_response({"error": "Workspaces not initialized"}, status=503)
    body = await request.json()
    channel = body.get("channel", "").strip()
    if not channel:
        return web.json_response({"error": "channel is required"}, status=400)
    await server.workspaces.add_channel(ws_id, channel)
    return web.json_response({"ok": True})


async def handle_workspace_members(request: web.Request) -> web.Response:
    """POST /api/workspaces/{id}/members -- add a member to workspace."""
    token = request.query.get("token")
    if not await verify_token(token):
        return web.json_response({"error": "Unauthorized"}, status=401)
    server: OrochiServer = request.app["orochi_server"]
    ws_id = request.match_info["id"]
    if not server.workspaces:
        return web.json_response({"error": "Workspaces not initialized"}, status=503)
    body = await request.json()
    agent_name = body.get("agent_name", "").strip()
    if not agent_name:
        return web.json_response({"error": "agent_name is required"}, status=400)
    role = body.get("role", "member")
    await server.workspaces.add_member(ws_id, agent_name, role)
    return web.json_response({"ok": True})


async def handle_create_invite(request: web.Request) -> web.Response:
    """POST /api/workspaces/{id}/invites -- create an invitation token."""
    token = request.query.get("token")
    if not await verify_token(token):
        return web.json_response({"error": "Unauthorized"}, status=401)
    server: OrochiServer = request.app["orochi_server"]
    ws_id = request.match_info["id"]
    if not server.workspaces:
        return web.json_response({"error": "Workspaces not initialized"}, status=503)
    body = await request.json()
    invite = await server.workspaces.create_invite(
        workspace_id=ws_id,
        created_by=body.get("created_by", "unknown"),
        role=body.get("role", "member"),
        max_uses=body.get("max_uses", 0),
        expires_hours=body.get("expires_hours", 0),
    )
    return web.json_response(invite, status=201)


async def handle_list_invites(request: web.Request) -> web.Response:
    """GET /api/workspaces/{id}/invites -- list workspace invitations."""
    server: OrochiServer = request.app["orochi_server"]
    ws_id = request.match_info["id"]
    if not server.workspaces:
        return web.json_response([], status=200)
    invites = await server.workspaces.list_invites(ws_id)
    return web.json_response(invites)


async def handle_redeem_invite(request: web.Request) -> web.Response:
    """POST /api/invites/redeem -- redeem an invitation token."""
    body = await request.json()
    invite_token = body.get("token", "").strip()
    agent_name = body.get("agent_name", "").strip()
    if not invite_token or not agent_name:
        return web.json_response({"error": "token and agent_name required"}, status=400)
    server: OrochiServer = request.app["orochi_server"]
    if not server.workspaces:
        return web.json_response({"error": "Workspaces not initialized"}, status=503)
    result = await server.workspaces.redeem_invite(invite_token, agent_name)
    if not result:
        return web.json_response(
            {"error": "Invalid, expired, or exhausted invite"}, status=400
        )
    return web.json_response(result)


async def handle_revoke_invite(request: web.Request) -> web.Response:
    """DELETE /api/workspaces/{id}/invites/{token} -- revoke an invitation."""
    auth_token = request.query.get("token")
    if not await verify_token(auth_token):
        return web.json_response({"error": "Unauthorized"}, status=401)
    server: OrochiServer = request.app["orochi_server"]
    invite_token = request.match_info["invite_token"]
    if not server.workspaces:
        return web.json_response({"error": "Workspaces not initialized"}, status=503)
    revoked = await server.workspaces.revoke_invite(invite_token)
    if not revoked:
        return web.json_response({"error": "Invite not found"}, status=404)
    return web.json_response({"ok": True})


async def handle_list_tokens(request: web.Request) -> web.Response:
    """GET /api/workspaces/{id}/tokens -- list workspace tokens."""
    server: OrochiServer = request.app["orochi_server"]
    ws_id = request.match_info["id"]
    if not server.workspaces:
        return web.json_response([], status=200)
    tokens = await server.workspaces.list_workspace_tokens(ws_id)
    return web.json_response(tokens)


async def handle_create_token(request: web.Request) -> web.Response:
    """POST /api/workspaces/{id}/tokens -- create a workspace token."""
    token = request.query.get("token")
    if not await verify_token(token):
        return web.json_response({"error": "Unauthorized"}, status=401)
    server: OrochiServer = request.app["orochi_server"]
    ws_id = request.match_info["id"]
    if not server.workspaces:
        return web.json_response({"error": "Workspaces not initialized"}, status=503)
    body = await request.json()
    label = body.get("label", "")
    result = await server.workspaces.create_workspace_token(ws_id, label=label)
    return web.json_response(result, status=201)


async def handle_revoke_token(request: web.Request) -> web.Response:
    """DELETE /api/workspaces/{id}/tokens/{token} -- revoke a workspace token."""
    auth_token = request.query.get("token")
    if not await verify_token(auth_token):
        return web.json_response({"error": "Unauthorized"}, status=401)
    server: OrochiServer = request.app["orochi_server"]
    ws_token = request.match_info["ws_token"]
    if not server.workspaces:
        return web.json_response({"error": "Workspaces not initialized"}, status=503)
    revoked = await server.workspaces.revoke_workspace_token(ws_token)
    if not revoked:
        return web.json_response({"error": "Token not found"}, status=404)
    return web.json_response({"ok": True})


def register_workspace_routes(app: web.Application) -> None:
    """Register workspace routes on the app."""
    app.router.add_get("/api/workspaces", handle_workspaces)
    app.router.add_post("/api/workspaces", handle_create_workspace)
    app.router.add_get("/api/workspaces/{id}", handle_workspace)
    app.router.add_delete("/api/workspaces/{id}", handle_delete_workspace)
    app.router.add_post("/api/workspaces/{id}/channels", handle_workspace_channels)
    app.router.add_post("/api/workspaces/{id}/members", handle_workspace_members)
    app.router.add_get("/api/workspaces/{id}/invites", handle_list_invites)
    app.router.add_post("/api/workspaces/{id}/invites", handle_create_invite)
    app.router.add_delete(
        "/api/workspaces/{id}/invites/{invite_token}", handle_revoke_invite
    )
    app.router.add_post("/api/invites/redeem", handle_redeem_invite)
    # Workspace tokens
    app.router.add_get("/api/workspaces/{id}/tokens", handle_list_tokens)
    app.router.add_post("/api/workspaces/{id}/tokens", handle_create_token)
    app.router.add_delete("/api/workspaces/{id}/tokens/{ws_token}", handle_revoke_token)
