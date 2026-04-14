"""Orochi WebSocket server -- agent communication hub."""

from __future__ import annotations

import asyncio
import json
import logging
import platform
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


def _log_task_exception(task: asyncio.Task) -> None:  # type: ignore[type-arg]
    """Log exceptions from fire-and-forget tasks instead of silently dropping them."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("Background task failed: %s", exc, exc_info=exc)


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
    workspace_id: str = ""
    multiplexer: str = ""
    status: str = "online"
    current_task: str = ""
    subagent_count: int = 0
    resources: dict[str, Any] = field(default_factory=dict)
    last_heartbeat: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    registered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class OrochiServer:
    """Main WebSocket server with channel routing and @mention delivery."""

    # Agents not heard from in this many seconds are considered stale.
    STALE_AGENT_SECONDS = 300  # 5 minutes

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
        # Workspace store (initialized after store.open)
        self.workspaces: Any = None
        # Background reaper task for stale agents
        self._reaper_task: asyncio.Task | None = None

    def start_reaper(self) -> None:
        """Start the background task that periodically removes stale agents."""
        if self._reaper_task is None or self._reaper_task.done():
            self._reaper_task = asyncio.create_task(self._reap_stale_agents_loop())
            self._reaper_task.add_done_callback(_log_task_exception)

    async def _reap_stale_agents_loop(self) -> None:
        """Periodically remove agents whose heartbeat is older than STALE_AGENT_SECONDS."""
        while True:
            await asyncio.sleep(60)
            self._reap_stale_agents()

    def _reap_stale_agents(self) -> None:
        """Remove agents that have not heartbeated within the staleness window."""
        now = datetime.now(timezone.utc)
        stale_names: list[str] = []
        for name, agent in self.agents.items():
            try:
                hb_dt = datetime.fromisoformat(agent.last_heartbeat)
                delta = (now - hb_dt).total_seconds()
            except (ValueError, TypeError):
                delta = float("inf")
            if delta > self.STALE_AGENT_SECONDS:
                stale_names.append(name)
        for name in stale_names:
            log.info(
                "Reaping stale agent: %s (no heartbeat for >%ds)",
                name,
                self.STALE_AGENT_SECONDS,
            )
            self._remove_agent(name)

    async def shutdown(self) -> None:
        log.info("Shutting down...")
        if self._reaper_task and not self._reaper_task.done():
            self._reaper_task.cancel()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        await self.store.close()
        log.info("Shutdown complete")

    async def _handle_connection(self, ws: ServerConnection) -> None:
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
                    agent_name = await self._handle_register(ws, msg, workspace_id)
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

    async def _handle_register(
        self, ws: Any, msg: Message, workspace_id: str = ""
    ) -> str:
        name = msg.sender
        channels = set(msg.payload.get("channels", ["#general"]))
        machine = msg.payload.get("machine", "")
        role = msg.payload.get("role", "")
        model = msg.payload.get("model", "")
        project = msg.payload.get("project", "")
        multiplexer = msg.payload.get("multiplexer", "")
        current_task = msg.payload.get("current_task", "") or ""
        try:
            subagent_count = int(msg.payload.get("subagent_count", 0) or 0)
        except (TypeError, ValueError):
            subagent_count = 0
        agent_id = msg.payload.get("agent_id", "")
        if not agent_id:
            machine_name = machine or platform.node()
            agent_id = f"{name}@{machine_name}"
        # Evict stale entry for the same agent name (reconnection)
        old = self.agents.pop(name, None)
        if old and old.ws is not ws:
            log.info("Replacing stale connection for agent: %s", name)
            for ch in old.channels:
                if ch in self.channels:
                    self.channels[ch].discard(name)
            try:
                await old.ws.close(4000, "Replaced by new connection")
            except Exception:
                pass
        # Evict stale agents from the same machine (handles agent renames).
        # Only remove agents that haven't heartbeated recently.
        if machine:
            now = datetime.now(timezone.utc)
            stale_from_machine: list[str] = []
            for other_name, other in self.agents.items():
                if other_name == name:
                    continue
                if other.machine == machine:
                    try:
                        hb_dt = datetime.fromisoformat(other.last_heartbeat)
                        delta = (now - hb_dt).total_seconds()
                    except (ValueError, TypeError):
                        delta = float("inf")
                    if delta > self.STALE_AGENT_SECONDS:
                        stale_from_machine.append(other_name)
            for stale_name in stale_from_machine:
                log.info(
                    "Evicting stale agent %s from machine %s (replaced by %s)",
                    stale_name,
                    machine,
                    name,
                )
                self._remove_agent(stale_name)
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
            multiplexer=multiplexer,
            workspace_id=workspace_id,
            status="online",
            current_task=current_task,
            subagent_count=subagent_count,
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
        # Determine sender_type: connected agents are "agent", others are "human"
        sender_type = "agent" if msg.sender in self.agents else "human"
        await self.store.save(
            msg_id=msg.id,
            ts=msg.ts,
            channel=channel,
            sender=msg.sender,
            content=msg.content,
            mentions=msg.mentions,
            metadata=metadata or None,
            sender_type=sender_type,
        )

        # Resolve sender's workspace for scoped routing
        sender_agent = self.agents.get(msg.sender)
        sender_ws = sender_agent.workspace_id if sender_agent else None

        # Deliver to channel subscribers in the same workspace
        delivered_to: set[str] = set()
        subscribers = set(self.channels.get(channel, set()))
        for agent_name in subscribers:
            if agent_name == msg.sender:
                continue
            agent = self.agents.get(agent_name)
            if agent and (sender_ws is None or agent.workspace_id == sender_ws):
                await self._send_to_agent(agent, msg)
                delivered_to.add(agent_name)

        # @mention routing -- same workspace only
        for mentioned in msg.mentions:
            if mentioned in delivered_to or mentioned == msg.sender:
                continue
            agent = self.agents.get(mentioned)
            if agent and (sender_ws is None or agent.workspace_id == sender_ws):
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

    async def _handle_presence(self, ws: Any, _msg: Message) -> None:
        online = {name: list(agent.channels) for name, agent in self.agents.items()}
        await ws.send(
            Message(
                type="presence",
                sender="orochi-server",
                payload={"agents": online},
            ).to_json()
        )

    _RESOURCE_KEYS = {
        "cpu_count",
        "cpu_model",
        "load_avg_1m",
        "load_avg_5m",
        "load_avg_15m",
        "mem_free_mb",
        "mem_total_mb",
        "mem_used_percent",
        "disk_used_percent",
    }

    async def _handle_heartbeat(self, msg: Message) -> None:
        agent = self.agents.get(msg.sender)
        if agent:
            agent.last_heartbeat = datetime.now(timezone.utc).isoformat()
            res = {k: v for k, v in msg.payload.items() if k in self._RESOURCE_KEYS}
            if res:
                agent.resources = res
            # Optional narrative fields carried in heartbeat payload so
            # simple clients do not need to send separate status_update
            # messages. Absent fields leave existing values untouched.
            if "current_task" in msg.payload:
                agent.current_task = str(msg.payload.get("current_task") or "")[:200]
            if "subagent_count" in msg.payload:
                try:
                    agent.subagent_count = int(msg.payload.get("subagent_count") or 0)
                except (TypeError, ValueError):
                    pass
            log.debug("Heartbeat from %s", msg.sender)

    async def _handle_status_update(self, msg: Message) -> None:
        agent = self.agents.get(msg.sender)
        if not agent:
            return
        for key in (
            "status",
            "current_task",
            "subagent_count",
            "machine",
            "role",
            "project",
            "agent_id",
        ):
            if key in msg.payload:
                value = msg.payload[key]
                if key == "subagent_count":
                    try:
                        value = int(value or 0)
                    except (TypeError, ValueError):
                        continue
                setattr(agent, key, value)
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
                    "subagent_count": agent.subagent_count,
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
            task = asyncio.create_task(
                self._broadcast_to_observers(
                    Message(
                        type="presence_change",
                        sender="orochi-server",
                        payload={"agent": name, "event": "disconnected"},
                    )
                )
            )
            task.add_done_callback(_log_task_exception)

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
                "multiplexer": a.multiplexer,
                "status": a.status,
                "current_task": a.current_task,
                "subagent_count": a.subagent_count,
                "resources": a.resources,
                "last_heartbeat": a.last_heartbeat,
                "workspace_id": a.workspace_id,
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

    async def get_all_channel_names(self) -> list[str]:
        """Return all known channel names (live subscriptions + stored history)."""
        live = set(self.channels.keys())
        stored = set(await self.store.distinct_channels())
        return sorted(live | stored)


# Backward compatibility: import main from _main module
def main() -> None:
    from scitex_orochi._main import main as _main

    _main()


if __name__ == "__main__":
    main()
