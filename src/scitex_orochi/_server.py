"""Orochi WebSocket server -- agent communication hub."""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import signal
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import websockets
from websockets.asyncio.server import Server, ServerConnection

from scitex_orochi._auth import extract_token_from_query, verify_token
from scitex_orochi._config import (
    GITEA_TOKEN,
    GITEA_URL,
    HOST,
    PORT,
    TELEGRAM_BRIDGE_ENABLED,
)
from scitex_orochi._gitea import GiteaClient
from scitex_orochi._models import Message
from scitex_orochi._store import MessageStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [orochi] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("orochi")


@dataclass
class Agent:
    name: str
    ws: Any  # ServerConnection
    channels: set[str] = field(default_factory=set)
    machine: str = ""
    role: str = ""
    model: str = ""
    agent_id: str = ""
    project: str = ""
    status: str = "online"
    current_task: str = ""
    resources: dict[str, Any] = field(default_factory=dict)
    last_heartbeat: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    registered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class OrochiServer:
    """Main WebSocket server with channel routing and @mention delivery."""

    def __init__(self, host: str = HOST, port: int = PORT) -> None:
        self.host = host
        self.port = port
        self.agents: dict[str, Agent] = {}
        self.channels: dict[str, set[str]] = {"#general": set()}
        self.store = MessageStore()
        self._server: Server | None = None
        # Observer connections (dashboard WebSocket clients)
        self._observers: set[Any] = set()
        # Message hooks (callables invoked after each channel message)
        self._message_hooks: list[Any] = []
        # Gitea client
        self.gitea = GiteaClient(base_url=GITEA_URL, token=GITEA_TOKEN)
        # Telegram bridge reference (set by main after setup)
        self.telegram_bridge: Any = None

    async def start(self) -> None:
        await self.store.open()
        self._server = await websockets.serve(
            self._handle_connection,
            self.host,
            self.port,
        )
        log.info("Orochi listening on ws://%s:%d", self.host, self.port)
        await asyncio.Future()  # run forever

    async def shutdown(self) -> None:
        log.info("Shutting down...")
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        await self.store.close()
        log.info("Shutdown complete")

    async def _handle_connection(self, ws: ServerConnection) -> None:
        # Auth check: extract token from query string
        token = extract_token_from_query(ws.request.path if ws.request else "")
        if not verify_token(token):
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
                    agent_name = await self._handle_register(ws, msg)
                elif msg.type == "message":
                    await self._handle_message(msg)
                elif msg.type == "subscribe":
                    await self._handle_subscribe(msg)
                elif msg.type == "unsubscribe":
                    await self._handle_unsubscribe(msg)
                elif msg.type == "query":
                    await self._handle_query(ws, msg)
                elif msg.type == "presence":
                    await self._handle_presence(ws, msg)
                elif msg.type == "heartbeat":
                    await self._handle_heartbeat(msg)
                elif msg.type == "status_update":
                    await self._handle_status_update(msg)
                elif msg.type == "gitea":
                    await self._handle_gitea(ws, msg)
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
                self._remove_agent(agent_name)

    async def _handle_register(self, ws: Any, msg: Message) -> str:
        name = msg.sender
        channels = set(msg.payload.get("channels", ["#general"]))
        machine = msg.payload.get("machine", "")
        role = msg.payload.get("role", "")
        model = msg.payload.get("model", "")
        project = msg.payload.get("project", "")
        agent_id = msg.payload.get("agent_id", "")
        if not agent_id:
            machine_name = machine or platform.node()
            agent_id = f"{name}@{machine_name}"
        now = datetime.now(timezone.utc).isoformat()
        self.agents[name] = Agent(
            name=name,
            ws=ws,
            channels=channels,
            machine=machine,
            role=role,
            model=model,
            agent_id=agent_id,
            project=project,
            status="online",
            current_task="",
            last_heartbeat=now,
            registered_at=now,
        )
        for ch in channels:
            self.channels.setdefault(ch, set()).add(name)
        log.info("Agent registered: %s (channels: %s)", name, channels)

        # Notify observers of presence change
        await self._broadcast_to_observers(
            Message(
                type="presence_change",
                sender="orochi-server",
                payload={
                    "agent": name,
                    "event": "connected",
                    "channels": list(channels),
                    "agent_id": agent_id,
                    "project": project,
                },
            )
        )
        return name

    async def _handle_message(self, msg: Message) -> None:
        channel = msg.channel
        if not channel:
            log.warning("Message from %s has no channel, dropping", msg.sender)
            return

        # Update heartbeat on message activity
        if msg.sender in self.agents:
            self.agents[msg.sender].last_heartbeat = datetime.now(
                timezone.utc
            ).isoformat()

        # Persist (include attachments in metadata)
        metadata = msg.payload.get("metadata") or {}
        attachments = msg.payload.get("attachments")
        if attachments:
            metadata["attachments"] = attachments
        await self.store.save(
            msg_id=msg.id,
            ts=msg.ts,
            channel=channel,
            sender=msg.sender,
            content=msg.content,
            mentions=msg.mentions,
            metadata=metadata or None,
        )

        # Deliver to channel subscribers (copy set to avoid RuntimeError
        # if _send_to_agent triggers _remove_agent which mutates the set)
        delivered_to: set[str] = set()
        subscribers = set(self.channels.get(channel, set()))
        for agent_name in subscribers:
            if agent_name == msg.sender:
                continue
            agent = self.agents.get(agent_name)
            if agent:
                await self._send_to_agent(agent, msg)
                delivered_to.add(agent_name)

        # @mention routing -- deliver to mentioned agents even if not subscribed
        for mentioned in msg.mentions:
            if mentioned in delivered_to or mentioned == msg.sender:
                continue
            agent = self.agents.get(mentioned)
            if agent:
                await self._send_to_agent(agent, msg)
                delivered_to.add(mentioned)

        log.info(
            "[%s] %s: %s (delivered to: %s)",
            channel,
            msg.sender,
            msg.content[:80],
            delivered_to or "nobody",
        )

        # Broadcast to observers
        await self._broadcast_to_observers(msg)

        # Invoke message hooks (e.g. Telegram bridge)
        for hook in self._message_hooks:
            try:
                await hook(msg)
            except Exception:
                log.exception("Message hook error")

    async def _handle_subscribe(self, msg: Message) -> None:
        channel = msg.payload.get("channel")
        if not channel:
            return
        agent = self.agents.get(msg.sender)
        if agent:
            agent.channels.add(channel)
            self.channels.setdefault(channel, set()).add(msg.sender)
            log.info("%s subscribed to %s", msg.sender, channel)

    async def _handle_unsubscribe(self, msg: Message) -> None:
        channel = msg.payload.get("channel")
        if not channel:
            return
        agent = self.agents.get(msg.sender)
        if agent:
            agent.channels.discard(channel)
            if channel in self.channels:
                self.channels[channel].discard(msg.sender)
            log.info("%s unsubscribed from %s", msg.sender, channel)

    async def _handle_query(self, ws: Any, msg: Message) -> None:
        channel = msg.payload.get("channel", "#general")
        since = msg.payload.get("since")
        limit = msg.payload.get("limit", 50)
        rows = await self.store.query(channel=channel, since=since, limit=limit)
        await ws.send(
            Message(
                type="message",
                sender="orochi-server",
                payload={"channel": channel, "content": "", "history": rows},
            ).to_json()
        )

    async def _handle_presence(self, ws: Any, msg: Message) -> None:
        online = {name: list(agent.channels) for name, agent in self.agents.items()}
        await ws.send(
            Message(
                type="presence",
                sender="orochi-server",
                payload={"agents": online},
            ).to_json()
        )

    async def _handle_heartbeat(self, msg: Message) -> None:
        agent = self.agents.get(msg.sender)
        if agent:
            agent.last_heartbeat = datetime.now(timezone.utc).isoformat()
            # Store system resource metrics if present in payload
            _RESOURCE_KEYS = {
                "cpu_count", "cpu_model",
                "load_avg_1m", "load_avg_5m", "load_avg_15m",
                "mem_free_mb", "mem_total_mb", "mem_used_percent",
                "disk_used_percent",
            }
            resource_data = {
                k: v for k, v in msg.payload.items() if k in _RESOURCE_KEYS
            }
            if resource_data:
                agent.resources = resource_data
            log.debug("Heartbeat from %s", msg.sender)

    async def _handle_status_update(self, msg: Message) -> None:
        agent = self.agents.get(msg.sender)
        if not agent:
            return
        if "status" in msg.payload:
            agent.status = msg.payload["status"]
        if "current_task" in msg.payload:
            agent.current_task = msg.payload["current_task"]
        if "machine" in msg.payload:
            agent.machine = msg.payload["machine"]
        if "role" in msg.payload:
            agent.role = msg.payload["role"]
        if "project" in msg.payload:
            agent.project = msg.payload["project"]
        if "agent_id" in msg.payload:
            agent.agent_id = msg.payload["agent_id"]
        agent.last_heartbeat = datetime.now(timezone.utc).isoformat()
        log.info("Status update from %s: %s", msg.sender, msg.payload)

        # Notify observers
        await self._broadcast_to_observers(
            Message(
                type="status_update",
                sender=msg.sender,
                payload={
                    "agent": msg.sender,
                    "status": agent.status,
                    "current_task": agent.current_task,
                    "machine": agent.machine,
                    "role": agent.role,
                    "agent_id": agent.agent_id,
                    "project": agent.project,
                },
            )
        )

    async def _handle_gitea(self, ws: Any, msg: Message) -> None:
        from scitex_orochi._gitea_handler import handle_gitea_message

        await handle_gitea_message(self.gitea, ws, msg)

    async def _send_to_agent(self, agent: Agent, msg: Message) -> None:
        try:
            await agent.ws.send(msg.to_json())
        except websockets.ConnectionClosed:
            self._remove_agent(agent.name)
        except Exception:
            log.exception("Failed to send to agent %s", agent.name)
            self._remove_agent(agent.name)

    def _remove_agent(self, name: str) -> None:
        agent = self.agents.pop(name, None)
        if agent:
            for ch in agent.channels:
                if ch in self.channels:
                    self.channels[ch].discard(name)
            log.info("Agent disconnected: %s", name)

            # Notify observers of presence change (fire-and-forget)
            asyncio.ensure_future(
                self._broadcast_to_observers(
                    Message(
                        type="presence_change",
                        sender="orochi-server",
                        payload={"agent": name, "event": "disconnected"},
                    )
                )
            )

    # -- Observer pattern for dashboard connections --

    def add_observer(self, ws: Any) -> None:
        """Add a dashboard WebSocket as an observer."""
        self._observers.add(ws)
        log.info("Observer connected (total: %d)", len(self._observers))

    def remove_observer(self, ws: Any) -> None:
        """Remove a dashboard WebSocket observer."""
        self._observers.discard(ws)
        log.info("Observer disconnected (total: %d)", len(self._observers))

    async def _broadcast_to_observers(self, msg: Message) -> None:
        """Send a message to all observer (dashboard) connections."""
        if not self._observers:
            return
        data = msg.to_json()
        dead: list[Any] = []
        for obs in self._observers:
            try:
                await obs.send_str(data)
            except Exception:
                dead.append(obs)
        for obs in dead:
            self._observers.discard(obs)

    def get_agents_info(self) -> list[dict]:
        """Return agent information for REST API."""
        return [
            {
                "name": a.name,
                "channels": list(a.channels),
                "machine": a.machine,
                "role": a.role,
                "model": a.model,
                "agent_id": a.agent_id,
                "project": a.project,
                "status": a.status,
                "current_task": a.current_task,
                "resources": a.resources,
                "last_heartbeat": a.last_heartbeat,
                "registered_at": a.registered_at,
            }
            for a in self.agents.values()
        ]

    def get_resources_info(self) -> dict[str, dict]:
        """Return latest resource metrics for all agents."""
        return {
            a.name: {
                "resources": a.resources,
                "last_heartbeat": a.last_heartbeat,
                "machine": a.machine,
                "status": a.status,
            }
            for a in self.agents.values()
        }

    def get_channels_info(self) -> dict[str, list[str]]:
        """Return channel membership for REST API."""
        return {ch: list(members) for ch, members in self.channels.items()}


def main() -> None:
    from scitex_orochi._config import DASHBOARD_PORT
    from scitex_orochi._web import create_web_app

    server = OrochiServer()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _shutdown_handler() -> None:
        loop.create_task(server.shutdown())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _shutdown_handler)

    telegram_bridge = None

    async def _run_all() -> None:
        nonlocal telegram_bridge
        await server.store.open()
        ws_server = await websockets.serve(
            server._handle_connection,
            server.host,
            server.port,
        )
        log.info("Orochi WebSocket listening on ws://%s:%d", server.host, server.port)
        from aiohttp import web as aio_web

        app = create_web_app(server)
        runner = aio_web.AppRunner(app)
        await runner.setup()
        site = aio_web.TCPSite(runner, server.host, DASHBOARD_PORT)
        await site.start()
        log.info("Orochi dashboard on http://%s:%d", server.host, DASHBOARD_PORT)
        # Telegram bridge (enabled via OROCHI_TELEGRAM_BRIDGE_ENABLED=true)
        if TELEGRAM_BRIDGE_ENABLED:
            from scitex_orochi._telegram_bridge import setup_telegram_bridge

            telegram_bridge = await setup_telegram_bridge(server)
            server.telegram_bridge = telegram_bridge
        await asyncio.Future()  # run forever

    try:
        loop.run_until_complete(_run_all())
    except asyncio.CancelledError:
        pass
    finally:
        if telegram_bridge:
            loop.run_until_complete(telegram_bridge.stop())
        loop.run_until_complete(server.shutdown())
        loop.close()


if __name__ == "__main__":
    main()
