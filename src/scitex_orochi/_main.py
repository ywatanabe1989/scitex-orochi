"""Orochi server entry point -- wires up WebSocket, HTTP dashboard, and bridges."""

from __future__ import annotations

import asyncio
import signal

import websockets

from scitex_orochi._config import (
    DASHBOARD_PORT,
    TELEGRAM_BRIDGE_ENABLED,
)
from scitex_orochi._server import OrochiServer, log
from scitex_orochi._web import create_web_app

# Protocol-level ping/pong: server sends pings every 30s, expects pong within 10s.
# This detects dead client connections (e.g. network drops) that the TCP layer
# may not notice for minutes.
WS_PING_INTERVAL = 30
WS_PING_TIMEOUT = 10


def main() -> None:
    import os
    import secrets

    from scitex_orochi._config import ADMIN_TOKEN

    # Ensure admin token exists (auto-generate if not set)
    admin_token = ADMIN_TOKEN
    if not admin_token:
        admin_token = secrets.token_urlsafe(32)
        os.environ["SCITEX_OROCHI_ADMIN_TOKEN"] = admin_token
        os.environ["SCITEX_OROCHI_TOKEN"] = admin_token
        log.info("Auto-generated admin token: %s", admin_token)

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
        # Initialize workspace model
        from scitex_orochi._workspaces import WorkspaceStore

        assert server.store._db is not None, (
            "MessageStore must be open before WorkspaceStore"
        )
        server.workspaces = WorkspaceStore(server.store._db)
        await server.workspaces.init_schema()
        ws_token = await server.workspaces.ensure_default_token()
        log.info("Default workspace token: %s", ws_token)
        ws_server = await websockets.serve(
            server._handle_connection,
            server.host,
            server.port,
            ping_interval=WS_PING_INTERVAL,
            ping_timeout=WS_PING_TIMEOUT,
        )
        log.info("Orochi WebSocket listening on ws://%s:%d", server.host, server.port)
        from aiohttp import web as aio_web

        app = create_web_app(server)
        runner = aio_web.AppRunner(app)
        await runner.setup()
        site = aio_web.TCPSite(runner, server.host, DASHBOARD_PORT)
        await site.start()
        log.info("Orochi dashboard on http://%s:%d", server.host, DASHBOARD_PORT)
        # Telegram bridge (enabled via SCITEX_OROCHI_TELEGRAM_BRIDGE_ENABLED=true)
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
