"""Orochi WebSocket client -- for agents to import."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import websockets

from orochi.config import HOST, OROCHI_TOKEN, PORT
from orochi.models import Message

log = logging.getLogger("orochi.client")


class OrochiClient:
    """Async WebSocket client for agent communication.

    Usage:
        async with OrochiClient("my-agent", channels=["#general"]) as client:
            await client.send("#general", "Hello from my-agent")

            async for msg in client.listen():
                print(f"[{msg.channel}] {msg.sender}: {msg.content}")
    """

    def __init__(
        self,
        name: str,
        host: str = HOST,
        port: int = PORT,
        channels: list[str] | None = None,
        token: str | None = None,
        machine: str = "",
        role: str = "",
        agent_id: str = "",
        project: str = "",
    ) -> None:
        import platform as _platform

        self.name = name
        self.channels = channels or ["#general"]
        self.machine = machine
        self.role = role
        self.project = project
        self.agent_id = agent_id
        if not self.agent_id:
            machine_name = machine or _platform.node()
            self.agent_id = f"{name}@{machine_name}"
        self._token = token or OROCHI_TOKEN
        query = f"?token={self._token}" if self._token else ""
        self.uri = f"ws://{host}:{port}{query}"
        self._ws = None
        self._listen_task: asyncio.Task | None = None

    async def connect(self) -> None:
        """Connect and register with the Orochi server."""
        self._ws = await websockets.connect(self.uri)
        reg = Message(
            type="register",
            sender=self.name,
            payload={
                "channels": self.channels,
                "machine": self.machine,
                "role": self.role,
                "agent_id": self.agent_id,
                "project": self.project,
            },
        )
        await self._ws.send(reg.to_json())
        # Wait for ack
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

    async def heartbeat(self) -> None:
        """Send a heartbeat to the server."""
        if not self._ws:
            raise RuntimeError("Not connected")
        msg = Message(type="heartbeat", sender=self.name)
        await self._ws.send(msg.to_json())

    async def update_status(
        self,
        status: str | None = None,
        current_task: str | None = None,
    ) -> None:
        """Send a status update to the server."""
        if not self._ws:
            raise RuntimeError("Not connected")
        payload: dict[str, str] = {}
        if status is not None:
            payload["status"] = status
        if current_task is not None:
            payload["current_task"] = current_task
        msg = Message(type="status_update", sender=self.name, payload=payload)
        await self._ws.send(msg.to_json())

    async def subscribe(self, channel: str) -> None:
        """Subscribe to an additional channel."""
        if not self._ws:
            raise RuntimeError("Not connected")
        msg = Message(
            type="subscribe",
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
        """Yield incoming messages. Skips ack/error types."""
        if not self._ws:
            raise RuntimeError("Not connected")
        try:
            async for raw in self._ws:
                try:
                    msg = Message.from_json(raw)
                except (json.JSONDecodeError, KeyError):
                    continue
                if msg.type in ("ack",):
                    continue
                yield msg
        except websockets.ConnectionClosed:
            log.warning("Connection closed")
