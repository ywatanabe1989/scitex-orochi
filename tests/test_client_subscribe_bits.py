"""Unit test — ``Client.subscribe(can_read=..., can_write=...)`` sends
the bit-split payload shape expected by the hub (lead msg#16884).

Exercises the client in isolation by replacing ``_ws`` with an async
mock that captures the frame string. No real server needed.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from scitex_orochi._client import OrochiClient


def _build_client() -> OrochiClient:
    """Minimal client instance with a mocked websocket."""
    c = OrochiClient.__new__(OrochiClient)
    c.name = "worker-bits-test"
    c._ws = AsyncMock()
    return c


@pytest.mark.asyncio
async def test_subscribe_defaults_send_both_bits_true():
    c = _build_client()
    await c.subscribe("#progress")
    c._ws.send.assert_awaited_once()
    raw = c._ws.send.call_args.args[0]
    frame = json.loads(raw)
    assert frame["type"] == "subscribe"
    payload = frame.get("payload") or {}
    assert payload.get("channel") == "#progress"
    assert payload.get("can_read") is True
    assert payload.get("can_write") is True


@pytest.mark.asyncio
async def test_subscribe_write_only_flag():
    c = _build_client()
    await c.subscribe("#ywatanabe", can_read=False, can_write=True)
    raw = c._ws.send.call_args.args[0]
    payload = json.loads(raw).get("payload") or {}
    assert payload.get("can_read") is False
    assert payload.get("can_write") is True


@pytest.mark.asyncio
async def test_subscribe_read_only_flag():
    c = _build_client()
    await c.subscribe("#listen", can_read=True, can_write=False)
    payload = json.loads(c._ws.send.call_args.args[0]).get("payload") or {}
    assert payload.get("can_read") is True
    assert payload.get("can_write") is False
