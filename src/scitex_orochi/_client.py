"""Orochi WebSocket client -- for agents to import."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import websockets

from scitex_orochi._config import HOST, OROCHI_TOKEN, PORT
from scitex_orochi._models import Message

log = logging.getLogger("orochi.client")


class OrochiClient:
    """Async WebSocket client for agent communication.

    Supports both standalone Orochi server (port 9559) and
    Django Channels backend (port 8559, /ws/agent/ endpoint).

    Usage:
        # Standalone server
        async with OrochiClient("my-agent", channels=["#general"]) as client:
            await client.send("#general", "Hello from my-agent")

        # Django Channels backend
        async with OrochiClient("my-agent", port=8559,
                                ws_path="/ws/agent/") as client:
            await client.send("#general", "Hello from my-agent")
    """

    def __init__(
        self,
        name: str,
        host: str = HOST,
        port: int = PORT,
        channels: list[str] | None = None,
        token: str | None = None,
        orochi_machine: str = "",
        role: str = "",
        agent_id: str = "",
        project: str = "",
        ws_path: str = "",
    ) -> None:
        import platform as _platform

        self.name = name
        self.channels = channels or ["#general"]
        self.orochi_machine = orochi_machine
        self.role = role
        self.project = project
        self.agent_id = agent_id
        if not self.agent_id:
            machine_name = orochi_machine or _platform.node()
            self.agent_id = f"{name}@{machine_name}"
        self._token = token or OROCHI_TOKEN
        self._ws_path = ws_path
        self._django_mode = bool(ws_path)

        # Build URI
        path = ws_path.rstrip("/") + "/" if ws_path else ""
        params = []
        if self._token:
            params.append(f"token={self._token}")
        if self._django_mode:
            params.append(f"agent={name}")
        query = "?" + "&".join(params) if params else ""
        self.uri = f"ws://{host}:{port}/{path.lstrip('/')}{query}"

        self._ws = None
        self._listen_task: asyncio.Task | None = None

    async def connect(self) -> None:
        """Connect and register with the Orochi server."""
        self._ws = await websockets.connect(self.uri)
        if self._django_mode:
            # Django Channels: send register, expect {"type": "registered"}
            import platform as _plat

            await self._ws.send(
                json.dumps(
                    {
                        "type": "register",
                        "payload": {
                            "channels": self.channels,
                            "orochi_machine": self.orochi_machine or _plat.node(),
                            "role": self.role,
                            "model": "",
                            "agent_id": self.agent_id,
                            "project": self.project,
                            "workdir": self.project,
                        },
                    }
                )
            )
            raw = await self._ws.recv()
            ack = json.loads(raw)
            if ack.get("type") == "error":
                raise ConnectionError(f"Registration failed: {ack}")
        else:
            # Standalone server: use Message model
            reg = Message(
                type="register",
                sender=self.name,
                payload={
                    "channels": self.channels,
                    "orochi_machine": self.orochi_machine,
                    "role": self.role,
                    "agent_id": self.agent_id,
                    "project": self.project,
                },
            )
            await self._ws.send(reg.to_json())
            raw = await self._ws.recv()
            ack = Message.from_json(raw)
            if ack.type == "error":
                raise ConnectionError(f"Registration failed: {ack.payload}")
        log.info("Connected as %s to %s", self.name, self.uri)

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def __aenter__(self) -> OrochiClient:
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.disconnect()

    async def send(
        self, channel: str, content: str, metadata: dict | None = None
    ) -> None:
        """Send a message to a channel."""
        if not self._ws:
            raise RuntimeError("Not connected")
        if self._django_mode:
            await self._ws.send(
                json.dumps(
                    {
                        "type": "message",
                        "payload": {
                            "channel": channel,
                            "text": content,
                            "metadata": metadata or {},
                        },
                    }
                )
            )
        else:
            msg = Message(
                type="message",
                sender=self.name,
                payload={
                    "channel": channel,
                    "content": content,
                    "metadata": metadata or {},
                },
            )
            await self._ws.send(msg.to_json())

    async def heartbeat(self, resources: dict[str, Any] | None = None) -> None:
        """Send a heartbeat to the server.

        Args:
            resources: Optional system metrics dict. If None and
                       auto_resources is not disabled, collects metrics
                       automatically via _resources.collect_metrics().
        """
        if not self._ws:
            raise RuntimeError("Not connected")
        payload: dict[str, Any] = {}
        if resources is not None:
            payload.update(resources)
        else:
            from scitex_orochi._resources import collect_metrics

            payload.update(collect_metrics())
        msg = Message(type="heartbeat", sender=self.name, payload=payload)
        await self._ws.send(msg.to_json())

    async def start_heartbeat(self, interval: int = 30) -> asyncio.Task:
        """Start a background task that sends heartbeats with resource metrics.

        Args:
            interval: Seconds between heartbeats (default: 30).

        Returns:
            The asyncio.Task — cancel it to stop heartbeats.
        """

        async def _loop() -> None:
            while True:
                try:
                    await self.heartbeat()
                except Exception:
                    log.warning("Heartbeat failed", exc_info=True)
                await asyncio.sleep(interval)

        task = asyncio.create_task(_loop())
        self._heartbeat_task = task
        return task

    def stop_heartbeat(self) -> None:
        """Cancel the background heartbeat task if running."""
        task = getattr(self, "_heartbeat_task", None)
        if task and not task.done():
            task.cancel()

    async def update_status(
        self,
        status: str | None = None,
        orochi_current_task: str | None = None,
    ) -> None:
        """Send a status update to the server."""
        if not self._ws:
            raise RuntimeError("Not connected")
        payload: dict[str, str] = {}
        if status is not None:
            payload["status"] = status
        if orochi_current_task is not None:
            payload["orochi_current_task"] = orochi_current_task
        msg = Message(type="status_update", sender=self.name, payload=payload)
        await self._ws.send(msg.to_json())

    async def subscribe(
        self,
        channel: str,
        *,
        can_read: bool = True,
        can_write: bool = True,
    ) -> None:
        """Subscribe to an additional channel (persisted server-side).

        ``can_read`` / ``can_write`` (lead msg#16884 bit-split) map to
        the two independent boolean bits on the persisted
        :class:`ChannelMembership` row. Both default to True (full
        read-write) so existing callers keep the pre-split behaviour.
        Examples:

        * ``can_read=True, can_write=True``  — full read-write (default)
        * ``can_read=True, can_write=False`` — read-only (listen, no post)
        * ``can_read=False, can_write=True`` — write-only (post digests
          without pulling the firehose back)
        """
        if not self._ws:
            raise RuntimeError("Not connected")
        msg = Message(
            type="subscribe",
            sender=self.name,
            payload={
                "channel": channel,
                "can_read": bool(can_read),
                "can_write": bool(can_write),
            },
        )
        await self._ws.send(msg.to_json())

    async def unsubscribe(self, channel: str) -> None:
        """Unsubscribe from a channel (persisted server-side)."""
        if not self._ws:
            raise RuntimeError("Not connected")
        msg = Message(
            type="unsubscribe",
            sender=self.name,
            payload={"channel": channel},
        )
        await self._ws.send(msg.to_json())

    async def query_history(
        self, channel: str, since: str | None = None, limit: int = 50
    ) -> list[dict]:
        """Query message history for a channel."""
        if not self._ws:
            raise RuntimeError("Not connected")
        msg = Message(
            type="query",
            sender=self.name,
            payload={"channel": channel, "since": since, "limit": limit},
        )
        await self._ws.send(msg.to_json())
        raw = await self._ws.recv()
        resp = Message.from_json(raw)
        return resp.payload.get("history", [])

    async def who(self) -> dict:
        """Query who is online."""
        if not self._ws:
            raise RuntimeError("Not connected")
        msg = Message(type="presence", sender=self.name)
        await self._ws.send(msg.to_json())
        raw = await self._ws.recv()
        resp = Message.from_json(raw)
        return resp.payload.get("agents", {})

    async def listen(self) -> AsyncIterator[Message]:
        """Yield incoming messages. Skips ack/error/registered types."""
        if not self._ws:
            raise RuntimeError("Not connected")
        try:
            async for raw in self._ws:
                try:
                    if self._django_mode:
                        data = json.loads(raw)
                        msg = Message(
                            type=data.get("type", "message"),
                            sender=data.get("sender", ""),
                            payload={
                                "channel": data.get("channel", ""),
                                "content": data.get("text", ""),
                                "metadata": data.get("metadata", {}),
                            },
                        )
                    else:
                        msg = Message.from_json(raw)
                except (json.JSONDecodeError, KeyError):
                    continue
                if msg.type in ("ack", "registered"):
                    continue
                yield msg
        except websockets.ConnectionClosed:
            log.warning("Connection closed")
