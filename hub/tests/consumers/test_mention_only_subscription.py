"""Tests for mention-only subscription filter (todo#406 Phase 2).

Verifies:
- subscribe with mention_only=True persists the flag in ChannelMembership
- _load_agent_mention_only_channels returns only mention-only channels
- chat_message is suppressed when channel is mention-only and agent not @-mentioned
- chat_message is forwarded when agent IS @-mentioned in a mention-only channel
- chat_message is always forwarded for non-mention-only channels
"""

from asgiref.sync import async_to_sync
from django.contrib.auth.models import User
from django.test import TestCase

from hub.models import Channel, ChannelMembership, Workspace


class MentionOnlyPersistenceTest(TestCase):
    def setUp(self):
        self.ws = Workspace.objects.create(name="mo-test-ws")

    def test_subscribe_mention_only_persists_flag(self):
        from hub.consumers import _persist_agent_subscription

        ok = async_to_sync(_persist_agent_subscription)(
            self.ws.id, "mamba-a", "#general", True, mention_only=True
        )
        self.assertTrue(ok)
        user = User.objects.get(username="agent-mamba-a")
        ch = Channel.objects.get(workspace=self.ws, name="#general")
        row = ChannelMembership.objects.get(user=user, channel=ch)
        self.assertTrue(row.mention_only)
        self.assertTrue(row.can_read)

    def test_subscribe_default_not_mention_only(self):
        from hub.consumers import _persist_agent_subscription

        async_to_sync(_persist_agent_subscription)(
            self.ws.id, "mamba-b", "#general", True
        )
        user = User.objects.get(username="agent-mamba-b")
        ch = Channel.objects.get(workspace=self.ws, name="#general")
        row = ChannelMembership.objects.get(user=user, channel=ch)
        self.assertFalse(row.mention_only)

    def test_load_mention_only_channels_returns_only_flagged(self):
        from hub.consumers import (
            _load_agent_mention_only_channels,
            _persist_agent_subscription,
        )

        async_to_sync(_persist_agent_subscription)(
            self.ws.id, "mamba-c", "#general", True, mention_only=True
        )
        async_to_sync(_persist_agent_subscription)(
            self.ws.id, "mamba-c", "#heads", True, mention_only=False
        )
        result = async_to_sync(_load_agent_mention_only_channels)(
            self.ws.id, "mamba-c"
        )
        self.assertIn("#general", result)
        self.assertNotIn("#heads", result)

    def test_resubscribe_can_flip_mention_only(self):
        from hub.consumers import (
            _load_agent_mention_only_channels,
            _persist_agent_subscription,
        )

        async_to_sync(_persist_agent_subscription)(
            self.ws.id, "mamba-d", "#general", True, mention_only=True
        )
        # Resubscribe without mention_only → should clear the flag
        async_to_sync(_persist_agent_subscription)(
            self.ws.id, "mamba-d", "#general", True, mention_only=False
        )
        result = async_to_sync(_load_agent_mention_only_channels)(
            self.ws.id, "mamba-d"
        )
        self.assertNotIn("#general", result)


class MentionOnlyFanOutFilterTest(TestCase):
    """Unit test the fan-out filter in AgentConsumer.chat_message.

    Patches channel layer so no real WS is needed; drives the consumer
    method directly via a simulated event dict.
    """

    def _make_consumer(self, agent_name, mention_only_channels):
        from unittest.mock import AsyncMock

        from hub.consumers._agent import AgentConsumer

        consumer = AgentConsumer.__new__(AgentConsumer)
        consumer.agent_name = agent_name
        consumer.workspace_id = 999
        consumer.agent_meta = {"channels": ["#general", "#heads"]}
        consumer._mention_only_channels = mention_only_channels
        consumer.send_json = AsyncMock()
        return consumer

    def test_mention_only_channel_suppressed_without_at_mention(self):
        consumer = self._make_consumer(
            "mamba-e", mention_only_channels={"#general"}
        )
        event = {
            "type": "chat.message",
            "channel": "#general",
            "kind": "group",
            "sender": "head-mba",
            "sender_type": "agent",
            "text": "This message has no mention",
        }
        async_to_sync(consumer.chat_message)(event)
        consumer.send_json.assert_not_called()

    def test_mention_only_channel_forwarded_when_mentioned(self):
        consumer = self._make_consumer(
            "mamba-e", mention_only_channels={"#general"}
        )
        event = {
            "type": "chat.message",
            "channel": "#general",
            "kind": "group",
            "sender": "head-mba",
            "sender_type": "agent",
            "text": "@mamba-e please do the thing",
        }
        async_to_sync(consumer.chat_message)(event)
        consumer.send_json.assert_called_once()

    def test_non_mention_only_channel_always_forwarded(self):
        consumer = self._make_consumer(
            "mamba-f", mention_only_channels=set()
        )
        event = {
            "type": "chat.message",
            "channel": "#general",
            "kind": "group",
            "sender": "head-mba",
            "sender_type": "agent",
            "text": "No mention here but channel is fully subscribed",
        }
        async_to_sync(consumer.chat_message)(event)
        consumer.send_json.assert_called_once()

    def test_mention_only_channel_not_in_meta_still_suppressed(self):
        consumer = self._make_consumer(
            "mamba-g", mention_only_channels={"#other"}
        )
        consumer.agent_meta = {"channels": ["#general"]}
        event = {
            "type": "chat.message",
            "channel": "#other",
            "kind": "group",
            "sender": "head-mba",
            "sender_type": "agent",
            "text": "channel not in agent_meta, gets suppressed by membership check first",
        }
        async_to_sync(consumer.chat_message)(event)
        consumer.send_json.assert_not_called()
