"""WebSocket connection dispatcher for OrochiServer."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import websockets

from scitex_orochi._auth import extract_token_from_query, verify_token
from scitex_orochi._models import Message

if TYPE_CHECKING:
    from websockets.asyncio.server import ServerConnection

    from scitex_orochi._server._base import Agent


class ConnectionMixin:
    """Per-connection authentication + message-type dispatch."""

    agents: dict[str, "Agent"]
    workspaces: Any

    async def _handle_connection(self, ws: "ServerConnection") -> None:
        token = extract_token_from_query(ws.request.path if ws.request else "")
        auth = await verify_token(token, self.workspaces)
        if not auth:
            await ws.send(
                Message(
                    type="error",
                    sender="orochi-server",
                    payload={
                        "code": "AUTH_FAILED",
                        "detail": "Invalid or missing token",
                    },
                ).to_json()
            )
            await ws.close(4001, "Authentication failed")
            return

        workspace_id = auth.workspace_id or ""
        agent_name: str | None = None
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                try:
                    msg = Message.from_json(raw)
                except (json.JSONDecodeError, KeyError) as exc:
                    await ws.send(
                        Message(
                            type="error",
                            sender="orochi-server",
                            payload={"code": "PARSE_ERROR", "detail": str(exc)},
                        ).to_json()
                    )
                    continue

                if msg.type == "register":
                    agent_name = await self._handle_register(  # type: ignore[attr-defined]
                        ws, msg, workspace_id
                    )
                elif msg.type == "message":
                    await self._handle_message(msg)  # type: ignore[attr-defined]
                elif msg.type == "subscribe":
                    await self._handle_subscribe(msg)  # type: ignore[attr-defined]
                elif msg.type == "unsubscribe":
                    await self._handle_unsubscribe(msg)  # type: ignore[attr-defined]
                elif msg.type == "query":
                    await self._handle_query(ws, msg)  # type: ignore[attr-defined]
                elif msg.type == "presence":
                    await self._handle_presence(ws, msg)  # type: ignore[attr-defined]
                elif msg.type == "heartbeat":
                    await self._handle_heartbeat(msg)  # type: ignore[attr-defined]
                elif msg.type == "status_update":
                    await self._handle_status_update(msg)  # type: ignore[attr-defined]
                elif msg.type == "gitea":
                    await self._handle_gitea(ws, msg)  # type: ignore[attr-defined]
                else:
                    await ws.send(
                        Message(
                            type="error",
                            sender="orochi-server",
                            payload={
                                "code": "UNKNOWN_TYPE",
                                "detail": f"Unknown message type: {msg.type}",
                            },
                        ).to_json()
                    )

                # Ack every valid message
                if msg.type != "error":
                    await ws.send(
                        Message(
                            type="ack",
                            sender="orochi-server",
                            payload={"status": "ok", "ref": msg.id},
                        ).to_json()
                    )

        except websockets.ConnectionClosed:
            pass
        finally:
            if agent_name and agent_name in self.agents:
                self._remove_agent(agent_name)  # type: ignore[attr-defined]
