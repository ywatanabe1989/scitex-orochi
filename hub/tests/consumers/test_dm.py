"""Tests for the Orochi hub Django app."""

import json  # noqa: F401
from unittest.mock import MagicMock, patch  # noqa: F401

from django.contrib.auth.models import User  # noqa: F401
from django.core.exceptions import ValidationError  # noqa: F401
from django.db import IntegrityError, transaction  # noqa: F401
from django.test import Client, TestCase  # noqa: F401

from hub import push as hub_push  # noqa: F401
from hub.models import (  # noqa: F401
    Channel,
    ChannelMembership,
    DMParticipant,
    Message,
    PushSubscription,
    Workspace,
    WorkspaceMember,
    WorkspaceToken,
    normalize_channel_name,
)


class DMConsumerRoutingTest(TestCase):
    """Spec v3 §3.1-§3.4 — DM routing, ACL, confidentiality filter (PR 2)."""

    def setUp(self):
        from hub.models import AgentProfile

        self.ws = Workspace.objects.create(name="dm-routing-ws")
        # Human users
        self.user_alice = User.objects.create_user(username="alice", password="x")
        self.user_bob = User.objects.create_user(username="bob", password="x")
        self.user_observer = User.objects.create_user(username="observer", password="x")
        self.mem_alice = WorkspaceMember.objects.create(
            workspace=self.ws, user=self.user_alice, role="member"
        )
        self.mem_bob = WorkspaceMember.objects.create(
            workspace=self.ws, user=self.user_bob, role="member"
        )
        self.mem_observer = WorkspaceMember.objects.create(
            workspace=self.ws, user=self.user_observer, role="member"
        )
        # A DM channel between alice and bob
        self.dm = Channel.objects.create(
            workspace=self.ws, name="dm:alice|bob", kind=Channel.KIND_DM
        )
        DMParticipant.objects.create(
            channel=self.dm,
            member=self.mem_alice,
            principal_type=DMParticipant.PRINCIPAL_HUMAN,
            identity_name="alice",
        )
        DMParticipant.objects.create(
            channel=self.dm,
            member=self.mem_bob,
            principal_type=DMParticipant.PRINCIPAL_HUMAN,
            identity_name="bob",
        )
        # An agent DM channel (agent-skill ↔ alice)
        self.agent_user = User.objects.create_user(username="agent-skill", password="x")
        self.mem_agent = WorkspaceMember.objects.create(
            workspace=self.ws, user=self.agent_user, role="member"
        )
        self.agent_profile = AgentProfile.objects.create(
            workspace=self.ws, name="skill"
        )
        self.dm_agent = Channel.objects.create(
            workspace=self.ws, name="dm:agent-skill|alice", kind=Channel.KIND_DM
        )
        DMParticipant.objects.create(
            channel=self.dm_agent,
            member=self.mem_agent,
            principal_type=DMParticipant.PRINCIPAL_AGENT,
            identity_name="skill",
        )
        DMParticipant.objects.create(
            channel=self.dm_agent,
            member=self.mem_alice,
            principal_type=DMParticipant.PRINCIPAL_HUMAN,
            identity_name="alice",
        )
        # A regular group channel for filter regression
        self.group_ch = Channel.objects.create(workspace=self.ws, name="#general")

    # ------------------------------------------------------------------
    # _ensure_agent_member
    # ------------------------------------------------------------------
    def test_ensure_agent_member_idempotent(self):
        """Calling ``_ensure_agent_member`` twice yields one row (spec §2.3)."""
        from asgiref.sync import async_to_sync

        from hub.consumers import _ensure_agent_member

        m1 = async_to_sync(_ensure_agent_member)(
            workspace_id=self.ws.id, agent_name="newbie"
        )
        m2 = async_to_sync(_ensure_agent_member)(
            workspace_id=self.ws.id, agent_name="newbie"
        )
        self.assertIsNotNone(m1)
        self.assertEqual(m1.id, m2.id)
        count = WorkspaceMember.objects.filter(
            workspace=self.ws, user__username="agent-newbie"
        ).count()
        self.assertEqual(count, 1)

    # ------------------------------------------------------------------
    # channel_acl.check_write_allowed — DM branch
    # ------------------------------------------------------------------
    def test_check_write_allowed_dm_participant_allowed(self):
        from hub.channel_acl import check_write_allowed

        self.assertTrue(
            check_write_allowed("alice", "dm:alice|bob", workspace_id=self.ws.id)
        )
        self.assertTrue(
            check_write_allowed("bob", "dm:alice|bob", workspace_id=self.ws.id)
        )

    def test_check_write_allowed_dm_non_participant_denied(self):
        from hub.channel_acl import check_write_allowed

        self.assertFalse(
            check_write_allowed("observer", "dm:alice|bob", workspace_id=self.ws.id)
        )

    def test_check_write_allowed_dm_principal_agent(self):
        """PRINCIPAL_AGENT DM — skill-manager carry-forward."""
        from hub.channel_acl import check_write_allowed

        # Agent sender — identity_name path
        self.assertTrue(
            check_write_allowed(
                "skill", "dm:agent-skill|alice", workspace_id=self.ws.id
            )
        )
        # Agent sender — bare username path (`agent-skill`)
        self.assertTrue(
            check_write_allowed(
                "agent-skill", "dm:agent-skill|alice", workspace_id=self.ws.id
            )
        )
        # Non-participant agent blocked
        self.assertFalse(
            check_write_allowed(
                "other", "dm:agent-skill|alice", workspace_id=self.ws.id
            )
        )

    def test_check_write_allowed_group_channel_unchanged(self):
        """Group channels still go through yaml (permissive default)."""
        from hub.channel_acl import check_write_allowed

        self.assertTrue(
            check_write_allowed("anyone", "#general", workspace_id=self.ws.id)
        )

    # ------------------------------------------------------------------
    # AgentConsumer.chat_message — DM forwarding filter
    # ------------------------------------------------------------------
    def _make_agent_consumer(self, member_id, agent_channels=None):
        from hub.consumers import AgentConsumer

        consumer = AgentConsumer.__new__(AgentConsumer)
        consumer.workspace_id = self.ws.id
        consumer.workspace_member_id = member_id
        consumer.agent_name = "test-agent"
        consumer.agent_meta = {"channels": agent_channels or []}
        consumer._sent = []

        async def fake_send(payload):
            consumer._sent.append(payload)

        consumer.send_json = fake_send
        return consumer

    def test_agent_chat_message_dm_forwarded_to_participant(self):
        from asgiref.sync import async_to_sync

        consumer = self._make_agent_consumer(self.mem_alice.id)
        event = {
            "type": "chat.message",
            "sender": "bob",
            "sender_type": "human",
            "channel": "dm:alice|bob",
            "kind": "dm",
            "text": "hi",
        }
        async_to_sync(consumer.chat_message)(event)
        self.assertEqual(len(consumer._sent), 1)
        self.assertEqual(consumer._sent[0]["channel"], "dm:alice|bob")

    def test_agent_chat_message_dm_dropped_for_non_participant(self):
        from asgiref.sync import async_to_sync

        consumer = self._make_agent_consumer(self.mem_observer.id)
        event = {
            "type": "chat.message",
            "sender": "bob",
            "sender_type": "human",
            "channel": "dm:alice|bob",
            "kind": "dm",
            "text": "hi",
        }
        async_to_sync(consumer.chat_message)(event)
        self.assertEqual(consumer._sent, [])

    def test_agent_chat_message_group_filter_unchanged(self):
        """Group channel: 90158bc agent_meta filter still applies."""
        from asgiref.sync import async_to_sync

        # Agent subscribed to #general only
        consumer = self._make_agent_consumer(
            self.mem_alice.id, agent_channels=["#general"]
        )
        good = {
            "type": "chat.message",
            "sender": "x",
            "channel": "#general",
            "text": "hi",
        }
        bad = {
            "type": "chat.message",
            "sender": "x",
            "channel": "#other",
            "text": "hi",
        }
        async_to_sync(consumer.chat_message)(good)
        async_to_sync(consumer.chat_message)(bad)
        self.assertEqual(len(consumer._sent), 1)
        self.assertEqual(consumer._sent[0]["channel"], "#general")

    def test_agent_chat_message_no_subs_receives_no_group(self):
        """Opt-in subscription: an agent with zero channels must not receive
        group broadcasts (the previous `agent_channels and ...` guard
        short-circuited the filter and let every group message through,
        which caused GitHub CI notifications routed to #progress to reach
        healer-ywata-note-win even though it was only subscribed to
        #general).
        """
        from asgiref.sync import async_to_sync

        consumer = self._make_agent_consumer(self.mem_alice.id, agent_channels=[])
        event = {
            "type": "chat.message",
            "sender": "github",
            "channel": "#progress",
            "text": "CI success",
        }
        async_to_sync(consumer.chat_message)(event)
        self.assertEqual(consumer._sent, [])

    # ------------------------------------------------------------------
    # DashboardConsumer.chat_message — confidentiality filter
    # ------------------------------------------------------------------
    def _make_dashboard_consumer(self, user):
        from hub.consumers import DashboardConsumer

        consumer = DashboardConsumer.__new__(DashboardConsumer)
        consumer.workspace_id = self.ws.id
        consumer.user = user
        consumer._sent = []

        async def fake_send(payload):
            consumer._sent.append(payload)

        consumer.send_json = fake_send
        return consumer

    def test_dashboard_drops_dm_for_non_participant(self):
        from asgiref.sync import async_to_sync

        consumer = self._make_dashboard_consumer(self.user_observer)
        event = {
            "type": "chat.message",
            "sender": "alice",
            "channel": "dm:alice|bob",
            "kind": "dm",
            "text": "hi",
        }
        async_to_sync(consumer.chat_message)(event)
        self.assertEqual(consumer._sent, [])

    def test_dashboard_forwards_dm_to_participant(self):
        from asgiref.sync import async_to_sync

        consumer = self._make_dashboard_consumer(self.user_alice)
        event = {
            "type": "chat.message",
            "sender": "bob",
            "channel": "dm:alice|bob",
            "kind": "dm",
            "text": "hi",
        }
        async_to_sync(consumer.chat_message)(event)
        self.assertEqual(len(consumer._sent), 1)

    def test_dashboard_drops_dm_for_token_user(self):
        """Token-authenticated dashboards (username='dashboard') never see DMs."""
        from asgiref.sync import async_to_sync

        class _TokenUser:
            username = "dashboard"
            id = None
            is_authenticated = True

        consumer = self._make_dashboard_consumer(_TokenUser())
        event = {
            "type": "chat.message",
            "sender": "alice",
            "channel": "dm:alice|bob",
            "kind": "dm",
            "text": "hi",
        }
        async_to_sync(consumer.chat_message)(event)
        self.assertEqual(consumer._sent, [])

    def test_dashboard_forwards_group_message(self):
        """Group channels still pass through unchanged."""
        from asgiref.sync import async_to_sync

        consumer = self._make_dashboard_consumer(self.user_observer)
        event = {
            "type": "chat.message",
            "sender": "anyone",
            "channel": "#general",
            "text": "hi",
        }
        async_to_sync(consumer.chat_message)(event)
        self.assertEqual(len(consumer._sent), 1)

    # ------------------------------------------------------------------
    # Rename signal — identity_name sync
    # ------------------------------------------------------------------
    def test_agent_profile_rename_updates_identity_name(self):
        """Renaming an AgentProfile updates DMParticipant.identity_name."""
        # Create a matching profile+participant setup where the
        # identity_name diverges on rename.
        self.agent_profile.name = "skill-renamed"
        # New underlying user for the rename target
        new_user = User.objects.create_user(
            username="agent-skill-renamed", password="x"
        )
        new_member = WorkspaceMember.objects.create(
            workspace=self.ws, user=new_user, role="member"
        )
        # Repoint the participant row to the new member before saving
        # — the signal uses the username of the current member.
        part = DMParticipant.objects.get(channel=self.dm_agent, member=self.mem_agent)
        part.member = new_member
        part.save()
        # Now fire the rename signal
        self.agent_profile.save()
        part.refresh_from_db()
        self.assertEqual(part.identity_name, "skill-renamed")

    def test_user_rename_updates_identity_name(self):
        """Renaming a human User updates DMParticipant.identity_name."""
        self.user_alice.username = "alice-renamed"
        self.user_alice.save()
        part = DMParticipant.objects.get(channel=self.dm, member=self.mem_alice)
        self.assertEqual(part.identity_name, "alice-renamed")

    # ------------------------------------------------------------------
    # DM broadcast path — skip workspace fanout
    # ------------------------------------------------------------------
    def test_dm_broadcast_skips_workspace_group(self):
        """Spec v3 §3.3 — DM writes must not hit workspace_<id>."""
        from asgiref.sync import async_to_sync

        from hub.consumers import AgentConsumer

        consumer = AgentConsumer.__new__(AgentConsumer)
        consumer.workspace_id = self.ws.id
        consumer.workspace_name = self.ws.name
        consumer.workspace_group = f"workspace_{self.ws.id}"
        consumer.agent_name = "alice"
        consumer.agent_meta = {"channels": ["dm:alice|bob"]}
        consumer.workspace_member_id = self.mem_alice.id

        sent = []

        class _FakeLayer:
            async def group_send(self, group, event):
                sent.append((group, event))

        consumer.channel_layer = _FakeLayer()

        async def fake_send_json(payload):
            pass

        consumer.send_json = fake_send_json

        # Stub _save_message to avoid DB writes for speed (not strictly
        # required — the call chain is async-safe — but keeps the test
        # focused on the fanout path).
        async def fake_save(**kwargs):
            return {"id": 1, "ts": "2026-01-01T00:00:00+00:00"}

        consumer._save_message = fake_save

        # Also stub mark_activity import chain
        async_to_sync(consumer.receive_json)(
            {
                "type": "message",
                "payload": {
                    "channel": "dm:alice|bob",
                    "content": "secret",
                },
            }
        )

        groups = [g for g, _ in sent]
        self.assertIn(
            _sanitize_group_name(f"channel_{self.ws.id}_dm:alice|bob"),
            groups,
        )
        self.assertNotIn(f"workspace_{self.ws.id}", groups)
        # All events should carry kind="dm"
        for _, ev in sent:
            self.assertEqual(ev.get("kind"), "dm")

    def test_group_broadcast_still_hits_workspace_group(self):
        """Regression: non-DM messages must still reach workspace_<id>."""
        from asgiref.sync import async_to_sync

        from hub.consumers import AgentConsumer

        consumer = AgentConsumer.__new__(AgentConsumer)
        consumer.workspace_id = self.ws.id
        consumer.workspace_name = self.ws.name
        consumer.workspace_group = f"workspace_{self.ws.id}"
        consumer.agent_name = "alice"
        consumer.agent_meta = {"channels": ["#general"]}
        consumer.workspace_member_id = self.mem_alice.id

        sent = []

        class _FakeLayer:
            async def group_send(self, group, event):
                sent.append((group, event))

        consumer.channel_layer = _FakeLayer()

        async def fake_send_json(payload):
            pass

        consumer.send_json = fake_send_json

        async def fake_save(**kwargs):
            return {"id": 1, "ts": "2026-01-01T00:00:00+00:00"}

        consumer._save_message = fake_save

        async_to_sync(consumer.receive_json)(
            {
                "type": "message",
                "payload": {
                    "channel": "#general",
                    "content": "public",
                },
            }
        )
        groups = [g for g, _ in sent]
        self.assertIn(f"workspace_{self.ws.id}", groups)


def _sanitize_group_name(name: str) -> str:
    """Test helper — mirrors hub.consumers._sanitize_group."""
    from hub.consumers import _sanitize_group

    return _sanitize_group(name)


# ---------------------------------------------------------------------------
# DM REST API + write-ACL tests (todo#60 PR 3, spec v3 §4 + §8)
# ---------------------------------------------------------------------------
