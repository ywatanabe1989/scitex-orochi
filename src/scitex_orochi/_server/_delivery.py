"""Outbound delivery, observer fan-out, and REST-info accessors."""

from __future__ import annotations

import asyncio
from typing import Any

import websockets

from scitex_orochi._models import Message
from scitex_orochi._server._base import Agent, _log_task_exception, log


class DeliveryMixin:
    """Send to a single agent, drop dead ones, fan out to dashboard observers."""

    agents: dict[str, Agent]
    channels: dict[str, set[str]]
    store: Any
    _observers: set[Any]

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
                "orochi_machine": a.orochi_machine,
                "role": a.role,
                "orochi_model": a.orochi_model,
                "agent_id": a.agent_id,
                "orochi_project": a.orochi_project,
                "multiplexer": a.multiplexer,
                "status": a.status,
                "orochi_current_task": a.orochi_current_task,
                "orochi_subagent_count": a.orochi_subagent_count,
                "resources": a.resources,
                "last_heartbeat": a.last_heartbeat,
                "workspace_id": a.workspace_id,
                "registered_at": a.registered_at,
            }
            for a in self.agents.values()
        ]

    def get_resources_info(self) -> dict[str, dict]:
        """Return latest resource orochi_metrics for all agents."""
        return {
            a.name: {
                "resources": a.resources,
                "last_heartbeat": a.last_heartbeat,
                "orochi_machine": a.orochi_machine,
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
