"""Thin async WebSocket wrapper for the worker-progress daemon.

We don't reuse ``scitex_orochi._client.OrochiClient`` because that
module lives under ``src/scitex_orochi/`` and would drag the whole
package (Django, channels, gitea helpers, ...) onto a daemon that only
needs ``websockets``. The handshake shape is intentionally kept in
lockstep with ``hub/consumers/_agent.py`` + ``hub/routing.py`` — if
the hub-side register format ever drifts, both sides must update.

The reconnect loop applies exponential backoff capped at 60 s.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any, AsyncIterator, Callable, Optional

log = logging.getLogger("worker-progress.client")


class HubWSClient:
    """Minimal hub WS client.

    Usage:

        client = HubWSClient(uri, agent_name="worker-progress")
        async for msg in client.run():
            ...  # dict frame from the hub

    ``run()`` owns the reconnect loop. If the WS drops, it sleeps with
    exponential backoff and yields again once the connection is
    re-established — the caller's iteration never has to handle
    reconnect explicitly.
    """

    # Backoff ladder: 1, 2, 4, 8, 16, 32, 60, 60, ... (cap 60 s).
    MIN_BACKOFF_S = 1.0
    MAX_BACKOFF_S = 60.0

    def __init__(
        self,
        uri: str,
        agent_name: str,
        channels: tuple[str, ...] = (),
        machine: str = "",
        project: str = "",
        dry_run: bool = False,
        ws_connect: Optional[Callable] = None,
    ) -> None:
        self.uri = uri
        self.agent_name = agent_name
        self.channels = list(channels)
        self.machine = machine
        self.project = project
        self.dry_run = dry_run
        # Injection point for tests.
        self._ws_connect = ws_connect
        self._ws: Any = None
        self._stopping = False

    # -- lifecycle ----------------------------------------------------

    async def stop(self) -> None:
        """Signal the run() loop to exit cleanly on next iteration."""
        self._stopping = True
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001 — best-effort close
                pass

    # -- outbound -----------------------------------------------------

    async def send_message(
        self, channel: str, text: str, metadata: Optional[dict] = None
    ) -> None:
        """Post a text message to a channel.

        When ``dry_run`` is set, the message is logged to stderr via
        the package logger instead of being sent — useful for install
        smoke-tests where you want to see what the daemon would emit.
        """
        if self.dry_run:
            log.info("DRY-RUN: would send to %s: %s", channel, text)
            return
        if self._ws is None:
            log.warning(
                "send_message dropped — WS not connected (channel=%s)", channel
            )
            return
        frame = {
            "type": "message",
            "payload": {
                "channel": channel,
                "text": text,
                "metadata": metadata or {},
            },
        }
        await self._ws.send(json.dumps(frame))

    async def subscribe(self, channel: str) -> None:
        """Persist a channel subscription server-side. No-op in dry-run."""
        if self.dry_run or self._ws is None:
            return
        frame = {
            "type": "subscribe",
            "payload": {"channel": channel},
        }
        await self._ws.send(json.dumps(frame))

    # -- main loop ----------------------------------------------------

    async def run(self) -> AsyncIterator[dict]:
        """Yield hub→client frames as ``dict``s, reconnecting forever.

        Never raises on normal disconnects; only exits when ``stop()``
        has been called.
        """
        backoff = self.MIN_BACKOFF_S
        while not self._stopping:
            try:
                async for frame in self._one_connection():
                    yield frame
                # Clean exit from _one_connection (EOF or close).
                if self._stopping:
                    break
                log.info("WS closed cleanly; reconnecting after %.1fs", backoff)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — log + retry
                log.warning(
                    "WS connection error: %s: %s — retrying in %.1fs",
                    type(e).__name__,
                    e,
                    backoff,
                )
            if self._stopping:
                break
            # Jittered backoff so a whole fleet coming up after an
            # outage doesn't stampede the hub.
            await asyncio.sleep(backoff + random.uniform(0, 0.5))
            backoff = min(self.MAX_BACKOFF_S, backoff * 2)
        log.info("WS run() loop exiting")

    async def _one_connection(self) -> AsyncIterator[dict]:
        """One connect → register → listen cycle."""
        connect = self._ws_connect
        if connect is None:
            import websockets  # deferred import so tests can stub

            connect = websockets.connect
        self._ws = await connect(self.uri)
        try:
            # Register frame. The hub ignores ``payload["channels"]``
            # (see hub/consumers/_agent_handlers.handle_register) and
            # hydrates from ChannelMembership rows instead — but we
            # include it for forward-compat + to match the other
            # clients on the wire.
            reg = {
                "type": "register",
                "payload": {
                    "channels": list(self.channels),
                    "machine": self.machine,
                    "role": "worker",
                    "model": "",
                    "agent_id": self.agent_name,
                    "project": self.project,
                    "workdir": self.project,
                },
            }
            await self._ws.send(json.dumps(reg))
            # Listen loop.
            async for raw in self._ws:
                if self._stopping:
                    return
                try:
                    data = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                if not isinstance(data, dict):
                    continue
                yield data
        finally:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
            self._ws = None
