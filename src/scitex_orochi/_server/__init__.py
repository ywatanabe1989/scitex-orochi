"""Orochi WebSocket server -- agent communication hub.

This package was split out from the previous monolithic ``_server.py``.
The public surface is unchanged: ``OrochiServer``, ``Agent``, ``log``,
and ``main`` are all importable as ``scitex_orochi._server.<name>``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from scitex_orochi._config import GITEA_TOKEN, GITEA_URL, HOST, PORT
from scitex_orochi._gitea import GiteaClient
from scitex_orochi._server._base import Agent, _log_task_exception, log
from scitex_orochi._server._connection import ConnectionMixin
from scitex_orochi._server._delivery import DeliveryMixin
from scitex_orochi._server._handlers import HandlersMixin
from scitex_orochi._server._lifecycle import LifecycleMixin
from scitex_orochi._store import MessageStore


class OrochiServer(
    LifecycleMixin,
    ConnectionMixin,
    HandlersMixin,
    DeliveryMixin,
):
    """Main WebSocket server with channel routing and @mention delivery."""

    def __init__(self, host: str = HOST, port: int = PORT) -> None:
        self.host = host
        self.port = port
        self.agents: dict[str, Agent] = {}
        self.channels: dict[str, set[str]] = {"#general": set()}
        self.store = MessageStore()
        self._server: Any = None
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


# Backward compatibility: import main from _main module
def main() -> None:
    from scitex_orochi._main import main as _main

    _main()


__all__ = [
    "Agent",
    "OrochiServer",
    "_log_task_exception",
    "log",
    "main",
]


if __name__ == "__main__":
    main()
