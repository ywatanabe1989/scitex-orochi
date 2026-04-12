"""Tests for the Orochi hub Django app."""

import json

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase

from hub.models import (
    Channel,
    DMParticipant,
    Message,
    Workspace,
    WorkspaceMember,
    WorkspaceToken,
)


class WorkspaceModelTest(TestCase):
    def test_create_workspace(self):
        ws = Workspace.objects.create(name="test-ws", description="Test workspace")
        self.assertEqual(str(ws), "test-ws")

    def test_workspace_token_auto_generated(self):
        ws = Workspace.objects.create(name="test-ws")
        token = WorkspaceToken.objects.create(workspace=ws, label="agent-1")
        self.assertTrue(token.token.startswith("wks_"))
        self.assertEqual(len(token.token), 36)  # "wks_" + 32 hex chars

    def test_channel_unique_per_workspace(self):
        ws = Workspace.objects.create(name="test-ws")
        Channel.objects.create(workspace=ws, name="#general")
        with self.assertRaises(Exception):
            Channel.objects.create(workspace=ws, name="#general")

    def test_message_creation(self):
        ws = Workspace.objects.create(name="test-ws")
        ch = Channel.objects.create(workspace=ws, name="#general")
        msg = Message.objects.create(
            workspace=ws, channel=ch, sender="agent-1", content="Hello"
        )
        self.assertEqual(msg.sender, "agent-1")
        self.assertEqual(msg.content, "Hello")
        self.assertIsNotNone(msg.ts)


class AuthTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser", password="testpass123"
        )
        self.ws = Workspace.objects.create(name="test-ws")
        WorkspaceMember.objects.create(workspace=self.ws, user=self.user, role="member")
        Channel.objects.create(workspace=self.ws, name="#general")

    def test_signin_page_loads(self):
        resp = self.client.get("/signin/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Orochi")
        self.assertContains(resp, "Sign In")

    def test_signup_page_loads(self):
        resp = self.client.get("/signup/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Sign Up")

    def test_login_backward_compat(self):
        resp = self.client.get("/login/")
        self.assertEqual(resp.status_code, 200)

    def test_unauthenticated_redirect(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/signin/", resp.url)

    def test_signin_success(self):
        resp = self.client.post(
            "/signin/", {"username": "testuser", "password": "testpass123"}
        )
        self.assertEqual(resp.status_code, 302)

    def test_signin_with_email(self):
        self.user.email = "test@example.com"
        self.user.save()
        resp = self.client.post(
            "/signin/", {"username": "test@example.com", "password": "testpass123"}
        )
        self.assertEqual(resp.status_code, 302)

    def test_signin_failure(self):
        resp = self.client.post(
            "/signin/", {"username": "testuser", "password": "wrongpass"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Invalid username or password")

    def test_signup_creates_user(self):
        resp = self.client.post(
            "/signup/",
            {
                "username": "newuser",
                "email": "new@example.com",
                "password": "SecurePass123!",
                "password2": "SecurePass123!",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(username="newuser").exists())

    def test_signup_password_mismatch(self):
        resp = self.client.post(
            "/signup/",
            {
                "username": "newuser",
                "email": "new@example.com",
                "password": "SecurePass123!",
                "password2": "different",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Passwords do not match")

    def test_signup_duplicate_username(self):
        resp = self.client.post(
            "/signup/",
            {
                "username": "testuser",
                "email": "other@example.com",
                "password": "SecurePass123!",
                "password2": "SecurePass123!",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "already taken")

    def test_signout(self):
        self.client.login(username="testuser", password="testpass123")
        resp = self.client.get("/signout/")
        self.assertEqual(resp.status_code, 302)
        # After signout, dashboard should redirect to signin
        resp2 = self.client.get("/")
        self.assertEqual(resp2.status_code, 302)

    def test_dashboard_requires_login(self):
        resp = self.client.get("/workspace/test-ws/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/signin/", resp.url)

    def test_dashboard_accessible_after_login(self):
        self.client.login(username="testuser", password="testpass123")
        resp = self.client.get("/workspace/test-ws/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "test-ws")

    def test_dashboard_no_access_without_membership(self):
        other_ws = Workspace.objects.create(name="other-ws")
        self.client.login(username="testuser", password="testpass123")
        resp = self.client.get("/workspace/other-ws/")
        self.assertEqual(resp.status_code, 403)

    def test_superuser_access_all_workspaces(self):
        admin = User.objects.create_superuser(username="admin", password="adminpass")
        other_ws = Workspace.objects.create(name="other-ws")
        self.client.login(username="admin", password="adminpass")
        resp = self.client.get("/workspace/other-ws/")
        self.assertEqual(resp.status_code, 200)


class RestApiTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="apiuser", password="apipass123")
        self.ws = Workspace.objects.create(name="api-ws")
        WorkspaceMember.objects.create(workspace=self.ws, user=self.user, role="member")
        self.ch = Channel.objects.create(workspace=self.ws, name="#general")
        self.client.login(username="apiuser", password="apipass123")

    def test_list_workspaces(self):
        resp = self.client.get("/api/workspaces/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "api-ws")

    def test_list_channels(self):
        resp = self.client.get("/api/workspace/api-ws/channels/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "#general")

    def test_post_message(self):
        resp = self.client.post(
            "/api/workspace/api-ws/messages/",
            data=json.dumps({"channel": "#general", "text": "Test message"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("id", data)

    def test_get_messages(self):
        Message.objects.create(
            workspace=self.ws,
            channel=self.ch,
            sender="bot",
            content="Hello world",
        )
        resp = self.client.get("/api/workspace/api-ws/messages/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["content"], "Hello world")

    def test_get_history(self):
        Message.objects.create(
            workspace=self.ws,
            channel=self.ch,
            sender="bot",
            content="History msg",
        )
        resp = self.client.get("/api/workspace/api-ws/history/general/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["content"], "History msg")

    def test_stats(self):
        resp = self.client.get("/api/workspace/api-ws/stats/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["workspace"], "api-ws")
        self.assertEqual(data["channel_count"], 1)

    def test_api_requires_auth(self):
        client = Client()  # not logged in
        resp = client.get("/api/workspaces/")
        self.assertEqual(resp.status_code, 302)


class WorkspaceTokenTest(TestCase):
    def test_token_resolves_to_workspace(self):
        ws = Workspace.objects.create(name="token-ws")
        token = WorkspaceToken.objects.create(workspace=ws, label="test")
        resolved = WorkspaceToken.objects.select_related("workspace").get(
            token=token.token
        )
        self.assertEqual(resolved.workspace.name, "token-ws")

    def test_invalid_token_raises(self):
        with self.assertRaises(WorkspaceToken.DoesNotExist):
            WorkspaceToken.objects.get(token="wks_invalid_token_here")


class DMSchemaTest(TestCase):
    """Schema-only tests for DM support (scitex-orochi#60 PR 1).

    Covers the Channel.kind field, the dm: prefix guard on group
    channels (spec v3 §9 Q5), and the DMParticipant model's
    unique_together + cascade-delete semantics (spec v3 §2.2).
    """

    def setUp(self):
        self.ws = Workspace.objects.create(name="dm-ws")
        self.user_a = User.objects.create_user(username="alice", password="x")
        self.user_b = User.objects.create_user(username="bob", password="x")
        self.mem_a = WorkspaceMember.objects.create(
            workspace=self.ws, user=self.user_a, role="member"
        )
        self.mem_b = WorkspaceMember.objects.create(
            workspace=self.ws, user=self.user_b, role="member"
        )

    def test_group_channel_rejects_dm_prefix(self):
        ch = Channel(workspace=self.ws, name="dm:alice|bob")  # default kind=group
        with self.assertRaises(ValidationError) as cm:
            ch.full_clean()
        self.assertIn("name", cm.exception.message_dict)

    def test_dm_channel_accepts_dm_prefix(self):
        ch = Channel(
            workspace=self.ws, name="dm:alice|bob", kind=Channel.KIND_DM
        )
        ch.full_clean()  # should not raise
        ch.save()
        self.assertEqual(ch.kind, "dm")

    def test_group_channel_default_kind_is_group(self):
        ch = Channel.objects.create(workspace=self.ws, name="#general")
        self.assertEqual(ch.kind, Channel.KIND_GROUP)

    def test_dm_participant_unique_together(self):
        ch = Channel.objects.create(
            workspace=self.ws, name="dm:alice|bob", kind=Channel.KIND_DM
        )
        DMParticipant.objects.create(
            channel=ch,
            member=self.mem_a,
            principal_type=DMParticipant.PRINCIPAL_HUMAN,
            identity_name="alice",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DMParticipant.objects.create(
                    channel=ch,
                    member=self.mem_a,
                    principal_type=DMParticipant.PRINCIPAL_HUMAN,
                    identity_name="alice",
                )

    def test_dm_participant_cascade_on_channel_delete(self):
        ch = Channel.objects.create(
            workspace=self.ws, name="dm:alice|bob", kind=Channel.KIND_DM
        )
        DMParticipant.objects.create(
            channel=ch,
            member=self.mem_a,
            principal_type=DMParticipant.PRINCIPAL_HUMAN,
            identity_name="alice",
        )
        DMParticipant.objects.create(
            channel=ch,
            member=self.mem_b,
            principal_type=DMParticipant.PRINCIPAL_HUMAN,
            identity_name="bob",
        )
        self.assertEqual(DMParticipant.objects.count(), 2)
        ch.delete()
        self.assertEqual(DMParticipant.objects.count(), 0)

    def test_dm_participant_cascade_on_member_delete(self):
        ch = Channel.objects.create(
            workspace=self.ws, name="dm:alice|bob", kind=Channel.KIND_DM
        )
        DMParticipant.objects.create(
            channel=ch,
            member=self.mem_a,
            principal_type=DMParticipant.PRINCIPAL_HUMAN,
            identity_name="alice",
        )
        DMParticipant.objects.create(
            channel=ch,
            member=self.mem_b,
            principal_type=DMParticipant.PRINCIPAL_HUMAN,
            identity_name="bob",
        )
        self.mem_a.delete()
        remaining = list(DMParticipant.objects.all())
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].identity_name, "bob")


class DMConsumerRoutingTest(TestCase):
    """Spec v3 §3.1-§3.4 — DM routing, ACL, confidentiality filter (PR 2)."""

    def setUp(self):
        from hub.models import AgentProfile

        self.ws = Workspace.objects.create(name="dm-routing-ws")
        # Human users
        self.user_alice = User.objects.create_user(username="alice", password="x")
        self.user_bob = User.objects.create_user(username="bob", password="x")
        self.user_observer = User.objects.create_user(
            username="observer", password="x"
        )
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
        self.agent_user = User.objects.create_user(
            username="agent-skill", password="x"
        )
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
        self.group_ch = Channel.objects.create(
            workspace=self.ws, name="#general"
        )

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
            check_write_allowed(
                "observer", "dm:alice|bob", workspace_id=self.ws.id
            )
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
        part = DMParticipant.objects.get(
            channel=self.dm_agent, member=self.mem_agent
        )
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
        part = DMParticipant.objects.get(
            channel=self.dm, member=self.mem_alice
        )
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
            _sanitize_group_name(
                f"channel_{self.ws.id}_dm:alice|bob"
            ),
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


class DmRestApiTest(TestCase):
    """Coverage for /api/workspace/<slug>/dms/ and the /messages/ ACL fix."""

    def setUp(self):
        self.client = Client()
        self.ws = Workspace.objects.create(name="dm-ws")

        # Two human callers + one synthetic agent user, all members.
        self.alice = User.objects.create_user(username="alice", password="x")
        self.bob = User.objects.create_user(username="bob", password="x")
        self.carol = User.objects.create_user(username="carol", password="x")
        self.agent_user = User.objects.create_user(
            username="agent-mamba-foo", password="x"
        )
        self.alice_m = WorkspaceMember.objects.create(
            workspace=self.ws, user=self.alice
        )
        self.bob_m = WorkspaceMember.objects.create(
            workspace=self.ws, user=self.bob
        )
        self.carol_m = WorkspaceMember.objects.create(
            workspace=self.ws, user=self.carol
        )
        self.agent_m = WorkspaceMember.objects.create(
            workspace=self.ws, user=self.agent_user
        )

    def _login(self, user):
        self.client.force_login(user)

    # ---- POST /dms/ ----------------------------------------------------

    def test_post_dms_creates_canonical_channel(self):
        self._login(self.alice)
        resp = self.client.post(
            "/api/workspace/dm-ws/dms/",
            data=json.dumps({"recipient": "human:bob"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        # Canonical name is dm:<sorted principal keys>
        expected = "dm:" + "|".join(sorted(["human:alice", "human:bob"]))
        self.assertEqual(data["name"], expected)
        self.assertEqual(data["kind"], "dm")
        self.assertEqual(len(data["other_participants"]), 1)
        self.assertEqual(data["other_participants"][0]["identity_name"], "bob")

        ch = Channel.objects.get(workspace=self.ws, name=expected)
        self.assertEqual(ch.kind, "dm")
        self.assertEqual(ch.dm_participants.count(), 2)

    def test_post_dms_is_idempotent(self):
        self._login(self.alice)
        url = "/api/workspace/dm-ws/dms/"
        body = json.dumps({"recipient": "human:bob"})
        r1 = self.client.post(url, data=body, content_type="application/json")
        r2 = self.client.post(url, data=body, content_type="application/json")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.json()["name"], r2.json()["name"])
        self.assertEqual(
            Channel.objects.filter(
                workspace=self.ws, kind="dm", name=r1.json()["name"]
            ).count(),
            1,
        )
        self.assertEqual(DMParticipant.objects.filter(channel__name=r1.json()["name"]).count(), 2)

    def test_post_dms_rejects_non_member(self):
        self._login(self.alice)
        resp = self.client.post(
            "/api/workspace/dm-ws/dms/",
            data=json.dumps({"recipient": "human:nobody"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_post_dms_routes_through_channel_clean(self):
        """The dm: prefix guard in Channel.clean() must run on create.

        Indirect test: create a DM, then try to create a *group* channel
        with the same dm: name — clean() must reject it. This proves the
        full_clean() path is wired up.
        """
        self._login(self.alice)
        resp = self.client.post(
            "/api/workspace/dm-ws/dms/",
            data=json.dumps({"recipient": "human:bob"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        canonical = resp.json()["name"]
        # Now build a group Channel with the same name and confirm
        # full_clean() rejects it (PR 1 guard).
        bad = Channel(
            workspace=self.ws, name=canonical, kind=Channel.KIND_GROUP
        )
        with self.assertRaises(ValidationError):
            bad.full_clean()

    def test_post_dms_agent_recipient(self):
        self._login(self.alice)
        resp = self.client.post(
            "/api/workspace/dm-ws/dms/",
            data=json.dumps({"recipient": "agent:mamba-foo"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertIn("agent:mamba-foo", data["name"])
        self.assertEqual(data["other_participants"][0]["type"], "agent")
        self.assertEqual(
            data["other_participants"][0]["identity_name"], "mamba-foo"
        )

    # ---- GET /dms/ -----------------------------------------------------

    def test_get_dms_only_returns_callers_dms(self):
        # alice <-> bob
        self._login(self.alice)
        self.client.post(
            "/api/workspace/dm-ws/dms/",
            data=json.dumps({"recipient": "human:bob"}),
            content_type="application/json",
        )
        # carol <-> bob (alice should NOT see this one)
        self.client.logout()
        self._login(self.carol)
        self.client.post(
            "/api/workspace/dm-ws/dms/",
            data=json.dumps({"recipient": "human:bob"}),
            content_type="application/json",
        )

        # Alice's view
        self.client.logout()
        self._login(self.alice)
        resp = self.client.get("/api/workspace/dm-ws/dms/")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()["dms"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["other_participants"][0]["identity_name"], "bob"
        )

    # ---- /messages/ write-ACL fix (§8 / todo#258) ----------------------

    def test_messages_post_dm_non_participant_forbidden(self):
        # Create a DM between alice <-> bob
        self._login(self.alice)
        r = self.client.post(
            "/api/workspace/dm-ws/dms/",
            data=json.dumps({"recipient": "human:bob"}),
            content_type="application/json",
        )
        dm_name = r.json()["name"]
        self.client.logout()

        # Carol (not a participant) tries to post into the DM channel.
        self._login(self.carol)
        resp = self.client.post(
            "/api/workspace/dm-ws/messages/",
            data=json.dumps({"channel": dm_name, "text": "sneaky"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(
            Message.objects.filter(channel__name=dm_name).count(), 0
        )

    def test_messages_post_dm_participant_allowed(self):
        self._login(self.alice)
        r = self.client.post(
            "/api/workspace/dm-ws/dms/",
            data=json.dumps({"recipient": "human:bob"}),
            content_type="application/json",
        )
        dm_name = r.json()["name"]

        resp = self.client.post(
            "/api/workspace/dm-ws/messages/",
            data=json.dumps({"channel": dm_name, "text": "hi bob"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(
            Message.objects.filter(channel__name=dm_name).count(), 1
        )

    def test_messages_post_group_channel_unaffected(self):
        Channel.objects.create(workspace=self.ws, name="#general")
        self._login(self.alice)
        resp = self.client.post(
            "/api/workspace/dm-ws/messages/",
            data=json.dumps({"channel": "#general", "text": "hello"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
