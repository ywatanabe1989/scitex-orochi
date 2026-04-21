"""Tests for scitex-orochi#451 — WS reconnect must not orphan channel subs.

Background. On a WS reconnect, the authoritative sequence is:

    client connect → server AgentConsumer.connect()
                       → joins workspace group
                       → joins DM groups from DMParticipant rows
                       → (#451) rehydrates persisted group memberships
                       → (#451) seeds agent_meta["channels"]
                       → (#451) consumer._registered = False
    client register   → server handle_register
                       → reloads group subs from DB + joins groups
                       → sets the full agent_meta payload
                       → flips consumer._registered = True
                       → sends a ``registered`` ack

Before #451, the connect() path joined DM groups but did NOT seed
agent_meta["channels"], so group-channel messages arriving between
connect and register were silently dropped by the chat_message filter.
If the client never sent ``register`` (bug, blip, race), the deafness
was permanent — the agent appeared connected but never received group
messages. This file covers the three contracts introduced by #451:

1. connect() pre-hydrates persisted group memberships + agent_meta.
2. handle_register remains idempotent under repeated calls (reconnect).
3. message-frame dispatch refuses writes from un-registered connections.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import async_to_sync
from django.contrib.auth.models import User
from django.test import TestCase

from hub.models import (
    Channel,
    ChannelMembership,
    DMParticipant,
    Workspace,
    WorkspaceMember,
)


def _fake_consumer(agent_name, workspace_id, dm_channels=()):
    """Return a minimal AgentConsumer stub suitable for the async helpers.

    ``prehydrate_channels`` and ``handle_register`` read a handful of
    attributes (``agent_name``, ``workspace_id``, ``channel_name``,
    ``channel_layer``, ``_dm_channel_names``) and call async methods on
    the channel layer. We mimic the surface with AsyncMock stubs so the
    async helpers can be driven from a sync test body via async_to_sync.
    """
    from hub.consumers._agent import AgentConsumer

    consumer = AgentConsumer.__new__(AgentConsumer)
    consumer.agent_name = agent_name
    consumer.workspace_id = workspace_id
    consumer.workspace_group = f"workspace_{workspace_id}"
    consumer.channel_name = f"test-ch-{agent_name}"
    consumer._dm_channel_names = list(dm_channels)
    consumer.channel_layer = MagicMock()
    consumer.channel_layer.group_add = AsyncMock()
    consumer.channel_layer.group_discard = AsyncMock()
    consumer.channel_layer.group_send = AsyncMock()
    consumer.send_json = AsyncMock()
    return consumer


class ReconnectPrehydrateTest(TestCase):
    """connect() must pre-join persisted group memberships and seed agent_meta."""

    def setUp(self):
        self.ws = Workspace.objects.create(name="reconnect-ws")
        self.ch_alpha = Channel.objects.create(workspace=self.ws, name="#alpha")
        self.ch_beta = Channel.objects.create(workspace=self.ws, name="#beta")
        self.agent_user = User.objects.create(username="agent-worker-r")
        ChannelMembership.objects.create(user=self.agent_user, channel=self.ch_alpha)
        ChannelMembership.objects.create(user=self.agent_user, channel=self.ch_beta)

    def test_prehydrate_joins_each_persisted_group_channel(self):
        from hub.consumers._agent_refresh import prehydrate_channels

        consumer = _fake_consumer("worker-r", self.ws.id)
        async_to_sync(prehydrate_channels)(consumer)

        joined = [
            call.args[0]
            for call in consumer.channel_layer.group_add.await_args_list
        ]
        # Both persisted channels must be group_added at connect.
        self.assertTrue(any("alpha" in g for g in joined))
        self.assertTrue(any("beta" in g for g in joined))
        # agent_meta["channels"] contains both persisted channels so the
        # chat_message membership filter lets group events through before
        # the client's register frame arrives.
        self.assertIn("#alpha", consumer.agent_meta["channels"])
        self.assertIn("#beta", consumer.agent_meta["channels"])

    def test_prehydrate_sets_registered_false(self):
        from hub.consumers._agent_refresh import prehydrate_channels

        consumer = _fake_consumer("worker-r", self.ws.id)
        async_to_sync(prehydrate_channels)(consumer)
        self.assertFalse(consumer._registered)

    def test_prehydrate_preserves_dm_channels_in_meta(self):
        from hub.consumers._agent_refresh import prehydrate_channels

        consumer = _fake_consumer(
            "worker-r", self.ws.id, dm_channels=["dm:worker-r|alice"]
        )
        async_to_sync(prehydrate_channels)(consumer)
        # DM channel is already joined by the earlier connect() step;
        # prehydrate must still include it in the seeded meta so the
        # chat_message DM filter + the visibility check both work.
        self.assertIn("dm:worker-r|alice", consumer.agent_meta["channels"])
        self.assertIn("#alpha", consumer.agent_meta["channels"])

    def test_prehydrate_swallows_db_errors_so_connect_does_not_abort(self):
        """DB hiccups at connect must NOT tear down the WebSocket.

        A DB blip would previously crash-bubble through connect() and
        close the socket, which is much worse than a transient deafness
        we can recover from when the client sends register. Ensure the
        helper logs and falls back to an empty channel list.
        """
        from hub.consumers._agent_refresh import prehydrate_channels

        consumer = _fake_consumer("worker-r", self.ws.id)
        with patch(
            "hub.consumers._agent_refresh._load_agent_channel_subs",
            side_effect=RuntimeError("db unavailable"),
        ):
            async_to_sync(prehydrate_channels)(consumer)

        # No groups joined — but also no unhandled exception.
        self.assertEqual(consumer.agent_meta["channels"], [])
        self.assertFalse(consumer._registered)


class ReconnectRegisterIdempotencyTest(TestCase):
    """handle_register must be safe to invoke on every reconnect."""

    def setUp(self):
        self.ws = Workspace.objects.create(name="idempotency-ws")
        self.ch_ops = Channel.objects.create(workspace=self.ws, name="#ops")
        self.agent_user = User.objects.create(username="agent-worker-s")
        ChannelMembership.objects.create(user=self.agent_user, channel=self.ch_ops)

    def _drive_register(self, consumer):
        from hub.consumers._agent_handlers import handle_register

        async_to_sync(handle_register)(consumer, {"type": "register", "payload": {}})

    def test_register_restores_meta_and_joins_groups_after_reconnect(self):
        """Simulate: connect → register → disconnect → reconnect → register."""
        from hub.consumers._agent_refresh import prehydrate_channels

        # First connection lifecycle.
        first = _fake_consumer("worker-s", self.ws.id)
        async_to_sync(prehydrate_channels)(first)
        self._drive_register(first)
        first_channels = list(first.agent_meta["channels"])
        self.assertIn("#ops", first_channels)
        self.assertTrue(first._registered)

        # Simulated disconnect is implicit — the consumer instance goes
        # away. A reconnect spins up a fresh consumer with no retained
        # state, then repeats the same sequence.
        second = _fake_consumer("worker-s", self.ws.id)
        async_to_sync(prehydrate_channels)(second)
        self._drive_register(second)

        # agent_meta["channels"] after reconnect must match the persisted
        # DB state (same set as first register).
        self.assertEqual(
            set(second.agent_meta["channels"]), set(first_channels)
        )
        self.assertTrue(second._registered)

        # group_add was called for each persisted channel on the SECOND
        # consumer (matters because Django Channels requires the re-join;
        # group membership is per-(group,channel_name) and the new
        # consumer has a different channel_name).
        joined = [
            call.args[0]
            for call in second.channel_layer.group_add.await_args_list
        ]
        self.assertTrue(any("ops" in g for g in joined))

    def test_register_repeated_on_same_consumer_is_idempotent(self):
        """Paranoid case: two register frames in a row on one consumer."""
        from hub.consumers._agent_refresh import prehydrate_channels

        consumer = _fake_consumer("worker-s", self.ws.id)
        async_to_sync(prehydrate_channels)(consumer)
        self._drive_register(consumer)
        first_channels = list(consumer.agent_meta["channels"])
        self._drive_register(consumer)
        self.assertEqual(
            list(consumer.agent_meta["channels"]), first_channels
        )
        # Ack sent twice (one per call) — clients are free to expect that.
        ack_frames = [
            call.args[0]
            for call in consumer.send_json.await_args_list
            if call.args and call.args[0].get("type") == "registered"
        ]
        self.assertEqual(len(ack_frames), 2)


class ReconnectMessageContractTest(TestCase):
    """message-frame dispatch must refuse writes from un-registered consumers.

    Before #451 the server accepted message frames regardless of
    registration state, so a client that reconnected and forgot to send
    register could still write (ACL-permitting) but be silently deaf to
    replies (not in any reply group). This breaks the contract loudly
    via an error ack instead.
    """

    def setUp(self):
        self.ws = Workspace.objects.create(name="contract-ws")

    def test_message_frame_rejected_when_not_registered(self):
        from hub.consumers._agent import AgentConsumer

        consumer = AgentConsumer.__new__(AgentConsumer)
        consumer.agent_name = "worker-t"
        consumer.workspace_id = self.ws.id
        consumer.workspace_group = f"workspace_{self.ws.id}"
        consumer.channel_name = "test-ch-worker-t"
        consumer._registered = False  # simulate missing-register state
        consumer.agent_meta = {"channels": []}
        consumer.send_json = AsyncMock()

        async_to_sync(consumer.receive_json)(
            {
                "type": "message",
                "payload": {"channel": "#general", "text": "hello"},
            }
        )

        # Message was NOT persisted nor broadcast — the dispatch bailed
        # before importing handle_agent_message. We can't inspect the
        # import directly, but an error ack on send_json is the contract.
        sent = [
            call.args[0] for call in consumer.send_json.await_args_list
        ]
        err = [
            frame for frame in sent if frame.get("type") == "error"
        ]
        self.assertTrue(err, "expected an error ack on un-registered send")
        self.assertEqual(err[0]["code"], "not_registered")

    def test_message_frame_accepted_after_register(self):
        """Positive control: once handle_register runs, messages flow."""
        from hub.consumers._agent import AgentConsumer

        consumer = AgentConsumer.__new__(AgentConsumer)
        consumer.agent_name = "worker-t"
        consumer.workspace_id = self.ws.id
        consumer.workspace_group = f"workspace_{self.ws.id}"
        consumer.channel_name = "test-ch-worker-t"
        consumer._registered = True  # handle_register already flipped this
        consumer.agent_meta = {"channels": ["#general"]}
        consumer.send_json = AsyncMock()

        with patch(
            "hub.consumers._agent_message.handle_agent_message",
            new=AsyncMock(),
        ) as mocked:
            async_to_sync(consumer.receive_json)(
                {
                    "type": "message",
                    "payload": {"channel": "#general", "text": "hello"},
                }
            )
            mocked.assert_awaited_once()


class ReconnectGroupDeliveryTest(TestCase):
    """End-to-end-ish: after reconnect a subscribed group message is delivered.

    Uses the real ``chat_message`` method on a hydrated fake consumer —
    mirrors the filter behaviour that was dropping messages pre-#451.
    """

    def setUp(self):
        self.ws = Workspace.objects.create(name="delivery-ws")
        self.ch_ops = Channel.objects.create(workspace=self.ws, name="#ops")
        self.agent_user = User.objects.create(username="agent-worker-u")
        ChannelMembership.objects.create(user=self.agent_user, channel=self.ch_ops)

    def test_group_message_delivered_after_reconnect_prehydrate(self):
        from hub.consumers._agent_refresh import prehydrate_channels

        consumer = _fake_consumer("worker-u", self.ws.id)
        async_to_sync(prehydrate_channels)(consumer)
        # NB: we do NOT call handle_register here — the fix guarantees
        # delivery works on the strength of prehydrate alone, which
        # defuses the "client hasn't sent register yet" race.

        event = {
            "type": "chat.message",
            "id": 1,
            "sender": "other-agent",
            "sender_type": "agent",
            "channel": "#ops",
            "kind": "group",
            "text": "hello ops",
            "ts": "2026-04-20T00:00:00Z",
            "metadata": {},
        }
        async_to_sync(consumer.chat_message)(event)

        sent = [
            call.args[0] for call in consumer.send_json.await_args_list
        ]
        delivered = [
            frame
            for frame in sent
            if frame.get("type") == "message" and frame.get("channel") == "#ops"
        ]
        self.assertTrue(
            delivered,
            "prehydrate must seed agent_meta so group messages pass the "
            "chat_message filter even before handle_register runs (#451)",
        )


class ReconnectDMDeliveryTest(TestCase):
    """DM delivery must keep working during the prehydrate → register window.

    DMs take the DMParticipant filter path (not the agent_meta filter),
    so they worked before #451 too. Regression guard so the new
    prehydrate path doesn't accidentally tighten DM filtering.
    """

    def setUp(self):
        self.ws = Workspace.objects.create(name="dm-delivery-ws")
        self.agent_user = User.objects.create(username="agent-worker-v")
        self.other_user = User.objects.create(username="someone")
        self.mem_agent = WorkspaceMember.objects.create(
            workspace=self.ws, user=self.agent_user, role="member"
        )
        self.mem_other = WorkspaceMember.objects.create(
            workspace=self.ws, user=self.other_user, role="member"
        )
        self.dm = Channel.objects.create(
            workspace=self.ws,
            name="dm:worker-v|someone",
            kind=Channel.KIND_DM,
        )
        DMParticipant.objects.create(
            channel=self.dm,
            member=self.mem_agent,
            principal_type=DMParticipant.PRINCIPAL_AGENT,
            identity_name="worker-v",
        )
        DMParticipant.objects.create(
            channel=self.dm,
            member=self.mem_other,
            principal_type=DMParticipant.PRINCIPAL_HUMAN,
            identity_name="someone",
        )

    def test_dm_delivered_after_reconnect_prehydrate(self):
        from hub.consumers._agent_refresh import prehydrate_channels

        consumer = _fake_consumer(
            "worker-v",
            self.ws.id,
            dm_channels=["dm:worker-v|someone"],
        )
        consumer.workspace_member_id = self.mem_agent.id
        async_to_sync(prehydrate_channels)(consumer)

        event = {
            "type": "chat.message",
            "id": 2,
            "sender": "someone",
            "sender_type": "human",
            "channel": "dm:worker-v|someone",
            "kind": "dm",
            "text": "hi",
            "ts": "2026-04-20T00:00:00Z",
            "metadata": {},
        }
        async_to_sync(consumer.chat_message)(event)

        delivered = [
            call.args[0]
            for call in consumer.send_json.await_args_list
            if call.args[0].get("type") == "message"
            and call.args[0].get("channel") == "dm:worker-v|someone"
        ]
        self.assertTrue(delivered)
