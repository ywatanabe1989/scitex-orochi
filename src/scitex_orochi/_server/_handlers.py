"""Per-message-type handlers for OrochiServer."""

from __future__ import annotations

import platform
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from scitex_orochi._models import Message
from scitex_orochi._server._base import RESOURCE_KEYS, Agent, log

if TYPE_CHECKING:
    pass


class HandlersMixin:
    """Implements the per-``msg.type`` handlers used by ``ConnectionMixin``."""

    agents: dict[str, Agent]
    channels: dict[str, set[str]]
    store: Any
    gitea: Any
    _message_hooks: list[Any]

    async def _handle_register(
        self, ws: Any, msg: Message, workspace_id: str = ""
    ) -> str:
        name = msg.sender
        # Channels are server-authoritative: agents register with no channels
        # and subscribe at runtime via MCP tools / REST API / web UI.
        # Legacy clients that still send a channels payload are respected
        # here for backward compatibility but new installs should send none.
        channels = set(msg.payload.get("channels", []))
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
                    if delta > self.STALE_AGENT_SECONDS:  # type: ignore[attr-defined]
                        stale_from_machine.append(other_name)
            for stale_name in stale_from_machine:
                log.info(
                    "Evicting stale agent %s from machine %s (replaced by %s)",
                    stale_name,
                    machine,
                    name,
                )
                self._remove_agent(stale_name)  # type: ignore[attr-defined]
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
        await self._broadcast_to_observers(  # type: ignore[attr-defined]
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
                await self._send_to_agent(agent, msg)  # type: ignore[attr-defined]
                delivered_to.add(agent_name)

        # @mention routing -- same workspace only
        for mentioned in msg.mentions:
            if mentioned in delivered_to or mentioned == msg.sender:
                continue
            agent = self.agents.get(mentioned)
            if agent and (sender_ws is None or agent.workspace_id == sender_ws):
                await self._send_to_agent(agent, msg)  # type: ignore[attr-defined]
                delivered_to.add(mentioned)

        log.info(
            "[%s] %s: %s (delivered to: %s)",
            channel,
            msg.sender,
            msg.content[:80],
            delivered_to or "nobody",
        )

        # Broadcast to observers
        await self._broadcast_to_observers(msg)  # type: ignore[attr-defined]

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

    # Backward-compat alias: kept as a class attribute so any external code
    # that referenced ``OrochiServer._RESOURCE_KEYS`` still works.
    _RESOURCE_KEYS = RESOURCE_KEYS

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
        await self._broadcast_to_observers(  # type: ignore[attr-defined]
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
