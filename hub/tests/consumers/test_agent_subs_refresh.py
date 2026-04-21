"""Tests for #282 — ChannelMembership signal → live AgentConsumer re-sync.

Covers both halves of the fix:

1. ``hub/signals.py`` — the ``ChannelMembership`` post_save / post_delete
   handlers dispatch an ``agent.subs_refresh`` frame to every live sibling
   WS connection for the affected agent (and ONLY for agent users).
2. ``hub/consumers/_agent.py`` — the ``agent_subs_refresh`` handler
   re-reads the DB, diffs against in-memory ``agent_meta["channels"]``,
   and performs the matching group_add / group_discard calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import async_to_sync
from django.contrib.auth.models import User
from django.test import TestCase

from hub.models import Channel, ChannelMembership, Workspace


def _fake_consumer(agent_name, workspace_id, channels, dm_channels=()):
    """Build a minimal consumer stub for the async handler under test."""
    from hub.consumers._agent import AgentConsumer

    consumer = AgentConsumer.__new__(AgentConsumer)
    consumer.agent_name = agent_name
    consumer.workspace_id = workspace_id
    consumer.workspace_group = f"workspace_{workspace_id}"
    consumer.channel_name = f"test-ch-{agent_name}"
    consumer._dm_channel_names = list(dm_channels)
    consumer.agent_meta = {"channels": list(channels)}
    consumer.channel_layer = MagicMock()
    consumer.channel_layer.group_add = AsyncMock()
    consumer.channel_layer.group_discard = AsyncMock()
    consumer.channel_layer.group_send = AsyncMock()
    return consumer


class ChannelMembershipSignalTest(TestCase):
    """Signal-fan-out half — ``hub/signals.py``."""

    def setUp(self):
        self.ws = Workspace.objects.create(name="signal-ws")
        self.ch = Channel.objects.create(workspace=self.ws, name="#ops")
        self.agent_user = User.objects.create(username="agent-worker-z")
        self.human_user = User.objects.create(username="alice")

    def _patched_send(self):
        """Patch the registry + channel layer used by the signal."""
        layer = MagicMock()
        layer.send = AsyncMock()
        return (
            patch(
                "hub.signals.get_channel_layer", return_value=layer
            ),
            patch(
                "hub.signals.list_sibling_channels",
                return_value=["ws-conn-1"],
            ),
            layer,
        )

    def test_save_fires_agent_subs_refresh_for_agent_user(self):
        p_layer, p_siblings, layer = self._patched_send()
        with p_layer, p_siblings, self.captureOnCommitCallbacks(execute=True):
            ChannelMembership.objects.create(
                user=self.agent_user, channel=self.ch
            )
        layer.send.assert_awaited_once()
        args, _kwargs = layer.send.call_args
        self.assertEqual(args[0], "ws-conn-1")
        payload = args[1]
        self.assertEqual(payload["type"], "agent.subs_refresh")
        self.assertEqual(payload["agent"], "worker-z")
        self.assertEqual(payload["workspace_id"], self.ws.id)

    def test_save_is_noop_for_human_user(self):
        p_layer, p_siblings, layer = self._patched_send()
        with p_layer, p_siblings, self.captureOnCommitCallbacks(execute=True):
            ChannelMembership.objects.create(
                user=self.human_user, channel=self.ch
            )
        layer.send.assert_not_awaited()

    def test_delete_fires_agent_subs_refresh(self):
        m = ChannelMembership.objects.create(
            user=self.agent_user, channel=self.ch
        )
        p_layer, p_siblings, layer = self._patched_send()
        with p_layer, p_siblings, self.captureOnCommitCallbacks(execute=True):
            m.delete()
        layer.send.assert_awaited_once()
        payload = layer.send.call_args[0][1]
        self.assertEqual(payload["type"], "agent.subs_refresh")

    def test_no_send_when_no_sibling_connections(self):
        layer = MagicMock()
        layer.send = AsyncMock()
        with patch(
            "hub.signals.get_channel_layer", return_value=layer
        ), patch(
            "hub.signals.list_sibling_channels", return_value=[]
        ), self.captureOnCommitCallbacks(execute=True):
            ChannelMembership.objects.create(
                user=self.agent_user, channel=self.ch
            )
        layer.send.assert_not_awaited()


class AgentSubsRefreshHandlerTest(TestCase):
    """Consumer handler half — ``AgentConsumer.agent_subs_refresh``."""

    def setUp(self):
        self.ws = Workspace.objects.create(name="handler-ws")
        self.ch_alpha = Channel.objects.create(
            workspace=self.ws, name="#alpha"
        )
        self.ch_beta = Channel.objects.create(
            workspace=self.ws, name="#beta"
        )
        self.agent_user = User.objects.create(username="agent-worker-q")

    def test_add_membership_joins_new_group_and_updates_meta(self):
        consumer = _fake_consumer(
            "worker-q", self.ws.id, channels=["#alpha"]
        )
        ChannelMembership.objects.create(
            user=self.agent_user, channel=self.ch_alpha
        )
        ChannelMembership.objects.create(
            user=self.agent_user, channel=self.ch_beta
        )

        async_to_sync(consumer.agent_subs_refresh)(
            {
                "type": "agent.subs_refresh",
                "agent": "worker-q",
                "workspace_id": self.ws.id,
            }
        )

        self.assertIn("#beta", consumer.agent_meta["channels"])
        consumer.channel_layer.group_add.assert_awaited()
        added_groups = [
            call.args[0]
            for call in consumer.channel_layer.group_add.await_args_list
        ]
        self.assertTrue(any("beta" in g for g in added_groups))

    def test_remove_membership_discards_group_and_updates_meta(self):
        ChannelMembership.objects.create(
            user=self.agent_user, channel=self.ch_alpha
        )
        consumer = _fake_consumer(
            "worker-q",
            self.ws.id,
            channels=["#alpha", "#beta"],  # in-memory stale
        )

        async_to_sync(consumer.agent_subs_refresh)(
            {
                "type": "agent.subs_refresh",
                "agent": "worker-q",
                "workspace_id": self.ws.id,
            }
        )

        self.assertNotIn("#beta", consumer.agent_meta["channels"])
        discarded = [
            call.args[0]
            for call in consumer.channel_layer.group_discard.await_args_list
        ]
        self.assertTrue(any("beta" in g for g in discarded))

    def test_refresh_preserves_dm_channels(self):
        consumer = _fake_consumer(
            "worker-q",
            self.ws.id,
            channels=["dm:worker-q|alice", "#alpha"],
            dm_channels=["dm:worker-q|alice"],
        )
        # No ChannelMembership rows → DB says agent is subscribed to nothing
        async_to_sync(consumer.agent_subs_refresh)(
            {
                "type": "agent.subs_refresh",
                "agent": "worker-q",
                "workspace_id": self.ws.id,
            }
        )
        self.assertIn("dm:worker-q|alice", consumer.agent_meta["channels"])
        # DM group must not be discarded by the refresh.
        discarded = [
            call.args[0]
            for call in consumer.channel_layer.group_discard.await_args_list
        ]
        self.assertFalse(any("dm:" in g for g in discarded))

    def test_refresh_skips_mismatched_workspace_event(self):
        consumer = _fake_consumer(
            "worker-q", self.ws.id, channels=["#alpha"]
        )
        ChannelMembership.objects.create(
            user=self.agent_user, channel=self.ch_beta
        )
        async_to_sync(consumer.agent_subs_refresh)(
            {
                "type": "agent.subs_refresh",
                "agent": "worker-q",
                "workspace_id": self.ws.id + 9999,
            }
        )
        # Event was for a different workspace — no DB lookup, no mutation.
        self.assertEqual(consumer.agent_meta["channels"], ["#alpha"])
        consumer.channel_layer.group_add.assert_not_awaited()
        consumer.channel_layer.group_discard.assert_not_awaited()

    def test_refresh_skips_other_agent_events(self):
        consumer = _fake_consumer(
            "worker-q", self.ws.id, channels=["#alpha"]
        )
        async_to_sync(consumer.agent_subs_refresh)(
            {
                "type": "agent.subs_refresh",
                "agent": "worker-other",
                "workspace_id": self.ws.id,
            }
        )
        self.assertEqual(consumer.agent_meta["channels"], ["#alpha"])
        consumer.channel_layer.group_add.assert_not_awaited()
        consumer.channel_layer.group_discard.assert_not_awaited()

    def test_refresh_broadcasts_agent_info_on_change(self):
        ChannelMembership.objects.create(
            user=self.agent_user, channel=self.ch_beta
        )
        consumer = _fake_consumer(
            "worker-q", self.ws.id, channels=["#alpha"]
        )
        with patch("hub.registry.register_agent") as reg:
            async_to_sync(consumer.agent_subs_refresh)(
                {
                    "type": "agent.subs_refresh",
                    "agent": "worker-q",
                    "workspace_id": self.ws.id,
                }
            )
            reg.assert_called_once()
        consumer.channel_layer.group_send.assert_awaited()
        sent_event = consumer.channel_layer.group_send.await_args.args[1]
        self.assertEqual(sent_event["type"], "agent.info")
        self.assertEqual(sent_event["agent"], "worker-q")
