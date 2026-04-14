"""Tests for AgentConsumer.chat_message channel filtering (todo#257).

Regression guard: chat messages are broadcast both to per-channel groups
and to the workspace group (for dashboard observers). Agents join the
workspace group on connect, so without filtering they receive every
message in the workspace regardless of SCITEX_OROCHI_CHANNELS. The
filter in chat_message drops events whose channel is not in the agent's
registered subscription set.
"""

import os
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "orochi.settings")
django = pytest.importorskip("django")
django.setup()

from hub.consumers import AgentConsumer  # noqa: E402


def _make_consumer(subscribed):
    consumer = AgentConsumer.__new__(AgentConsumer)
    consumer.agent_meta = {"channels": subscribed}
    consumer.send_json = AsyncMock()
    return consumer


def _event(channel):
    return {
        "id": 1,
        "sender": "peer-agent",
        "sender_type": "agent",
        "channel": channel,
        "text": "hi",
        "ts": "2026-04-13T00:00:00Z",
        "metadata": {},
    }


@pytest.mark.asyncio
async def test_drops_unsubscribed_channel():
    consumer = _make_consumer(["#agent", "#progress"])
    await consumer.chat_message(_event("#ywatanabe"))
    consumer.send_json.assert_not_called()


@pytest.mark.asyncio
async def test_forwards_subscribed_channel():
    consumer = _make_consumer(["#agent", "#progress"])
    await consumer.chat_message(_event("#agent"))
    consumer.send_json.assert_awaited_once()
    forwarded = consumer.send_json.await_args.args[0]
    assert forwarded["channel"] == "#agent"
    assert forwarded["type"] == "message"


@pytest.mark.asyncio
async def test_forwards_when_no_subscription_metadata():
    # Before register() arrives, agent_meta may be missing or empty.
    # Fail-open preserves pre-fix behavior during that window rather
    # than silently dropping early messages.
    consumer = AgentConsumer.__new__(AgentConsumer)
    consumer.send_json = AsyncMock()
    await consumer.chat_message(_event("#agent"))
    consumer.send_json.assert_awaited_once()


@pytest.mark.asyncio
async def test_forwards_when_empty_subscription_list():
    consumer = _make_consumer([])
    await consumer.chat_message(_event("#agent"))
    consumer.send_json.assert_awaited_once()
