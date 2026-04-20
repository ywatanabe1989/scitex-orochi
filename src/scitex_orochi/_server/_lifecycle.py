"""Lifecycle (startup, stale-agent reaper, shutdown) for OrochiServer."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from scitex_orochi._server._base import _log_task_exception, log

if TYPE_CHECKING:
    from websockets.asyncio.server import Server

    from scitex_orochi._server._base import Agent


class LifecycleMixin:
    """Stale-agent reaper and graceful shutdown."""

    # Agents not heard from in this many seconds are considered stale.
    STALE_AGENT_SECONDS = 300  # 5 minutes

    # Attribute hints (provided by composing class)
    agents: dict[str, "Agent"]
    _server: "Server | None"
    _reaper_task: "asyncio.Task | None"
    store: Any

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
            self._remove_agent(name)  # type: ignore[attr-defined]

    async def shutdown(self) -> None:
        log.info("Shutting down...")
        if self._reaper_task and not self._reaper_task.done():
            self._reaper_task.cancel()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        await self.store.close()
        log.info("Shutdown complete")
