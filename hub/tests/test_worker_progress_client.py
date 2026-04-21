"""Tests for the worker-progress WS client stub (todo#272).

We never make a real WS call. Instead we inject a fake ``connect``
into :class:`HubWSClient` and verify:
  - register frame is sent at connection time with the expected payload
  - ``send_message`` emits a well-formed ``message`` frame
  - ``dry_run=True`` short-circuits ``send_message`` without calling ws
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest import TestCase

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_SERVER = _REPO_ROOT / "scripts" / "server"
if str(_SCRIPTS_SERVER) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_SERVER))

from worker_progress_pkg._client import HubWSClient  # noqa: E402


class FakeWS:
    """Minimal duck-typed WS replacement for the client tests."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.incoming: list[str] = []
        self.closed = False

    async def send(self, raw: str) -> None:
        self.sent.append(raw)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        async def gen():
            for item in list(self.incoming):
                yield item

        return gen()


def _fake_connect_factory(ws: FakeWS):
    async def _connect(_uri, *_a, **_kw):
        return ws

    return _connect


class HubWSClientTest(TestCase):
    def test_dry_run_send_message_does_not_touch_ws(self):
        client = HubWSClient(
            uri="wss://example.invalid/ws/agent/?token=x&agent=worker-progress",
            agent_name="worker-progress",
            dry_run=True,
        )

        async def go():
            await client.send_message("#ywatanabe", "hello")

        asyncio.run(go())
        self.assertIsNone(client._ws)

    def test_one_connection_sends_register_then_yields_frames(self):
        ws = FakeWS()
        ws.incoming = [
            json.dumps(
                {
                    "type": "message",
                    "channel": "#progress",
                    "sender": "github",
                    "text": "CI started",
                }
            )
        ]
        client = HubWSClient(
            uri="wss://example.invalid/ws/agent/?token=x&agent=worker-progress",
            agent_name="worker-progress",
            channels=("#progress", "#heads", "#ywatanabe"),
            ws_connect=_fake_connect_factory(ws),
        )

        async def go():
            frames = []
            async for frame in client._one_connection():
                frames.append(frame)
            return frames

        frames = asyncio.run(go())
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["channel"], "#progress")

        # Register frame must have been sent before any receive.
        self.assertGreaterEqual(len(ws.sent), 1)
        reg = json.loads(ws.sent[0])
        self.assertEqual(reg["type"], "register")
        self.assertEqual(reg["payload"]["agent_id"], "worker-progress")
        self.assertEqual(reg["payload"]["role"], "worker")
        self.assertIn("#progress", reg["payload"]["channels"])
        # Connection must have been closed at the end of _one_connection.
        self.assertTrue(ws.closed)

    def test_send_message_frame_shape(self):
        ws = FakeWS()
        client = HubWSClient(
            uri="wss://example.invalid/ws/agent/?token=x&agent=worker-progress",
            agent_name="worker-progress",
            ws_connect=_fake_connect_factory(ws),
        )

        async def go():
            # Manually attach the WS (skip the register dance).
            client._ws = ws
            await client.send_message("#ywatanabe", "digest line", {"k": "v"})

        asyncio.run(go())
        self.assertEqual(len(ws.sent), 1)
        frame = json.loads(ws.sent[0])
        self.assertEqual(frame["type"], "message")
        self.assertEqual(frame["payload"]["channel"], "#ywatanabe")
        self.assertEqual(frame["payload"]["text"], "digest line")
        self.assertEqual(frame["payload"]["metadata"], {"k": "v"})
