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
    normalize_channel_name,
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


class ChannelNameNormalizeTest(TestCase):
    """Coverage for the todo#326 write-side normalization."""

    def test_normalize_helper_adds_hash(self):
        self.assertEqual(normalize_channel_name("general"), "#general")
        self.assertEqual(normalize_channel_name("progress"), "#progress")

    def test_normalize_helper_passthrough_canonical(self):
        self.assertEqual(normalize_channel_name("#general"), "#general")
        self.assertEqual(normalize_channel_name("#agent"), "#agent")

    def test_normalize_helper_passthrough_dm(self):
        self.assertEqual(
            normalize_channel_name("dm:agent:head|human:ywatanabe"),
            "dm:agent:head|human:ywatanabe",
        )

    def test_normalize_helper_strips_whitespace(self):
        self.assertEqual(normalize_channel_name("  general  "), "#general")

    def test_normalize_helper_rejects_empty(self):
        with self.assertRaises(ValueError):
            normalize_channel_name("")
        with self.assertRaises(ValueError):
            normalize_channel_name("   ")
        with self.assertRaises(ValueError):
            normalize_channel_name(None)

    def test_channel_save_normalizes_bare_name(self):
        ws = Workspace.objects.create(name="ws-norm")
        ch = Channel.objects.create(workspace=ws, name="general")
        ch.refresh_from_db()
        self.assertEqual(ch.name, "#general")

    def test_channel_save_passes_canonical_through(self):
        ws = Workspace.objects.create(name="ws-norm-2")
        ch = Channel.objects.create(workspace=ws, name="#agent")
        ch.refresh_from_db()
        self.assertEqual(ch.name, "#agent")

    def test_channel_save_does_not_touch_dm_kind(self):
        ws = Workspace.objects.create(name="ws-norm-3")
        # DM channels keep their dm: prefix even on save.
        ch = Channel.objects.create(
            workspace=ws,
            name="dm:agent:head|human:ywatanabe",
            kind=Channel.KIND_DM,
        )
        ch.refresh_from_db()
        self.assertEqual(ch.name, "dm:agent:head|human:ywatanabe")

    def test_get_or_create_with_bare_then_canonical_collapses(self):
        """The legacy duplication scenario: an agent posts to ``general``
        then another posts to ``#general``. With the save() normalizer
        and call-site normalize_channel_name(), both must converge on
        the same row."""
        ws = Workspace.objects.create(name="ws-collapse")
        a, _ = Channel.objects.get_or_create(
            workspace=ws, name=normalize_channel_name("general")
        )
        b, _ = Channel.objects.get_or_create(
            workspace=ws, name=normalize_channel_name("#general")
        )
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(
            Channel.objects.filter(workspace=ws).count(), 1
        )


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


# ── Web Push (todo#263) ─────────────────────────────────────────────────

from unittest.mock import patch, MagicMock

from hub.models import PushSubscription
from hub import push as hub_push


class PushSubscriptionModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pushy", password="pw")
        self.ws = Workspace.objects.create(name="push-ws")

    def test_create(self):
        sub = PushSubscription.objects.create(
            user=self.user,
            workspace=self.ws,
            endpoint="https://fcm.example/abc",
            p256dh="p" * 80,
            auth="a" * 20,
        )
        self.assertEqual(sub.user, self.user)
        self.assertEqual(sub.channels, [])

    def test_endpoint_unique(self):
        PushSubscription.objects.create(
            user=self.user,
            endpoint="https://fcm.example/x",
            p256dh="p",
            auth="a",
        )
        with self.assertRaises(Exception):
            with transaction.atomic():
                PushSubscription.objects.create(
                    user=self.user,
                    endpoint="https://fcm.example/x",
                    p256dh="p2",
                    auth="a2",
                )

    def test_cascade_on_user_delete(self):
        PushSubscription.objects.create(
            user=self.user,
            endpoint="https://fcm.example/y",
            p256dh="p",
            auth="a",
        )
        self.user.delete()
        self.assertEqual(PushSubscription.objects.count(), 0)


class PushApiTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="ua", password="pw")
        self.ws = Workspace.objects.create(name="push-ws")
        WorkspaceMember.objects.create(workspace=self.ws, user=self.user, role="member")

    def test_vapid_key_endpoint(self):
        from django.test import override_settings

        with override_settings(SCITEX_OROCHI_VAPID_PUBLIC="PUB123"):
            resp = self.client.get("/api/push/vapid-key")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["public_key"], "PUB123")

    def test_vapid_key_unconfigured(self):
        from django.test import override_settings

        with override_settings(SCITEX_OROCHI_VAPID_PUBLIC=""):
            resp = self.client.get("/api/push/vapid-key")
            self.assertEqual(resp.json()["public_key"], "")

    def test_subscribe_requires_auth(self):
        resp = self.client.post(
            "/api/push/subscribe",
            data=json.dumps({"endpoint": "x", "keys": {"p256dh": "p", "auth": "a"}}),
            content_type="application/json",
        )
        self.assertIn(resp.status_code, (302, 401, 403))

    def test_subscribe_creates_row_idempotent(self):
        self.client.login(username="ua", password="pw")
        body = json.dumps(
            {
                "endpoint": "https://fcm.example/sub1",
                "keys": {"p256dh": "p256", "auth": "auth1"},
                "channels": ["#general"],
            }
        )
        r1 = self.client.post(
            "/api/push/subscribe", data=body, content_type="application/json"
        )
        self.assertEqual(r1.status_code, 200)
        r2 = self.client.post(
            "/api/push/subscribe", data=body, content_type="application/json"
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(PushSubscription.objects.count(), 1)
        sub = PushSubscription.objects.get()
        self.assertEqual(sub.channels, ["#general"])

    def test_unsubscribe_removes_row(self):
        self.client.login(username="ua", password="pw")
        PushSubscription.objects.create(
            user=self.user,
            endpoint="https://fcm.example/zz",
            p256dh="p",
            auth="a",
        )
        resp = self.client.post(
            "/api/push/unsubscribe",
            data=json.dumps({"endpoint": "https://fcm.example/zz"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PushSubscription.objects.count(), 0)


class PushFanoutTest(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="pw")
        self.bob = User.objects.create_user(username="bob", password="pw")
        self.ws = Workspace.objects.create(name="fanout-ws")
        self.sub_bob = PushSubscription.objects.create(
            user=self.bob,
            workspace=self.ws,
            endpoint="https://fcm.example/bob",
            p256dh="p",
            auth="a",
        )
        self.sub_alice = PushSubscription.objects.create(
            user=self.alice,
            workspace=self.ws,
            endpoint="https://fcm.example/alice",
            p256dh="p",
            auth="a",
        )

    def _settings(self):
        from django.test import override_settings

        return override_settings(
            SCITEX_OROCHI_VAPID_PUBLIC="pub",
            SCITEX_OROCHI_VAPID_PRIVATE="priv",
            SCITEX_OROCHI_VAPID_SUBJECT="mailto:test@example.com",
        )

    def test_excludes_sender(self):
        with self._settings(), patch("pywebpush.webpush") as mock_wp:
            n = hub_push.send_push_to_subscribers(
                workspace_id=self.ws.id,
                channel="#general",
                sender="alice",
                content="hi",
                message_id=1,
            )
            # Only bob should be notified
            self.assertEqual(n, 1)
            self.assertEqual(mock_wp.call_count, 1)
            args, kwargs = mock_wp.call_args
            self.assertIn("bob", kwargs["subscription_info"]["endpoint"])

    def test_channel_filter(self):
        self.sub_bob.channels = ["#ops"]
        self.sub_bob.save()
        with self._settings(), patch("pywebpush.webpush") as mock_wp:
            hub_push.send_push_to_subscribers(
                workspace_id=self.ws.id,
                channel="#general",
                sender="alice",
                content="hi",
                message_id=1,
            )
            # Bob filtered out by channel mismatch; alice excluded as sender
            self.assertEqual(mock_wp.call_count, 0)

    def test_stale_410_deleted(self):
        from pywebpush import WebPushException

        resp = MagicMock()
        resp.status_code = 410
        exc = WebPushException("gone", response=resp)
        with self._settings(), patch("pywebpush.webpush", side_effect=exc):
            hub_push.send_push_to_subscribers(
                workspace_id=self.ws.id,
                channel="#general",
                sender="alice",
                content="bye",
                message_id=2,
            )
        self.assertFalse(
            PushSubscription.objects.filter(pk=self.sub_bob.pk).exists()
        )

    def test_skips_when_unconfigured(self):
        from django.test import override_settings

        with override_settings(
            SCITEX_OROCHI_VAPID_PUBLIC="", SCITEX_OROCHI_VAPID_PRIVATE=""
        ):
            with patch("pywebpush.webpush") as mock_wp:
                n = hub_push.send_push_to_subscribers(
                    workspace_id=self.ws.id,
                    channel="#general",
                    sender="alice",
                    content="x",
                )
                self.assertEqual(n, 0)
                mock_wp.assert_not_called()


class AgentMetaOAuthRegisterTest(TestCase):
    """todo#265: /api/agents/register/ accepts OAuth public metadata fields.

    The agent_meta.py --push heartbeat surfaces the authenticated
    Claude Code OAuth account's PUBLIC metadata (email, org,
    subscription state) so the Agents/Activity tab can show which
    account each agent is running under and detect out_of_credits.

    Strict security contract: the 9 whitelisted fields are read only
    from ``~/.claude.json`` via a whitelist extractor. No tokens,
    refresh tokens, credentials, or secrets are ever read or accepted.
    """

    def setUp(self):
        self.client = Client()
        self.ws = Workspace.objects.create(name="oauth-test-ws")
        self.token = WorkspaceToken.objects.create(
            workspace=self.ws, label="oauth-test"
        )

    def _post(self, payload):
        return self.client.post(
            "/api/agents/register/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_register_accepts_oauth_fields(self):
        from hub.registry import _agents as _reg_agents
        from hub.registry import get_agents

        _reg_agents.clear()
        payload = {
            "token": self.token.token,
            "name": "oauth-agent-1",
            "machine": "MBA",
            "oauth_email": "alice@example.org",
            "oauth_org_name": "Acme Research",
            "oauth_account_uuid": "uuid-111",
            "oauth_display_name": "Alice",
            "billing_type": "subscription",
            "has_available_subscription": True,
            "usage_disabled_reason": "",
            "has_extra_usage_enabled": False,
            "subscription_created_at": "2025-01-01T00:00:00Z",
        }
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 200)
        agents = get_agents(workspace_id=self.ws.id)
        match = [a for a in agents if a["name"] == "oauth-agent-1"]
        self.assertEqual(len(match), 1)
        a = match[0]
        self.assertEqual(a["oauth_email"], "alice@example.org")
        self.assertEqual(a["oauth_org_name"], "Acme Research")
        self.assertEqual(a["oauth_account_uuid"], "uuid-111")
        self.assertEqual(a["oauth_display_name"], "Alice")
        self.assertEqual(a["billing_type"], "subscription")
        self.assertEqual(a["has_available_subscription"], True)
        self.assertEqual(a["has_extra_usage_enabled"], False)
        self.assertEqual(a["subscription_created_at"], "2025-01-01T00:00:00Z")

    def test_register_out_of_credits_flag(self):
        """usage_disabled_reason='out_of_credits' is persisted for UI."""
        from hub.registry import _agents as _reg_agents
        from hub.registry import get_agents

        _reg_agents.clear()
        resp = self._post({
            "token": self.token.token,
            "name": "oauth-agent-2",
            "usage_disabled_reason": "out_of_credits",
        })
        self.assertEqual(resp.status_code, 200)
        a = [x for x in get_agents(workspace_id=self.ws.id)
             if x["name"] == "oauth-agent-2"][0]
        self.assertEqual(a["usage_disabled_reason"], "out_of_credits")

    def test_register_missing_oauth_fields_defaults(self):
        """Legacy agents without oauth fields still register cleanly."""
        from hub.registry import _agents as _reg_agents
        from hub.registry import get_agents

        _reg_agents.clear()
        resp = self._post({
            "token": self.token.token,
            "name": "legacy-agent",
        })
        self.assertEqual(resp.status_code, 200)
        a = [x for x in get_agents(workspace_id=self.ws.id)
             if x["name"] == "legacy-agent"][0]
        self.assertEqual(a["oauth_email"], "")
        self.assertEqual(a["oauth_org_name"], "")
        self.assertIsNone(a["has_available_subscription"])

    def test_register_does_not_echo_tokens(self):
        """Even if a client tries to POST token-like fields under
        arbitrary keys, the registry's strict whitelist drops them.

        This is the server-side belt to the client-side braces
        (read_oauth_metadata's whitelist extractor + assert).
        """
        from hub.registry import _agents as _reg_agents
        from hub.registry import get_agents

        _reg_agents.clear()
        resp = self._post({
            "token": self.token.token,
            "name": "leak-test",
            "oauth_email": "bob@example.org",
            # Hostile fields — must NOT end up in the registry.
            "accessToken": "sk-ant-oat01-leaked",
            "refreshToken": "sk-ant-ort01-leaked",
            "apiKey": "sk-ant-api03-leaked",
            "claudeAiOauth": {"accessToken": "sk-ant-oat01-leaked"},
            "credentials": "bearer leaked",
        })
        self.assertEqual(resp.status_code, 200)
        a = [x for x in get_agents(workspace_id=self.ws.id)
             if x["name"] == "leak-test"][0]
        flat = json.dumps(a).lower()
        for forbidden in (
            "sk-ant-oat01-leaked",
            "sk-ant-ort01-leaked",
            "sk-ant-api03-leaked",
            "bearer leaked",
        ):
            self.assertNotIn(forbidden, flat,
                             f"leaked token material {forbidden!r} in registry entry")
        # And no forbidden keys in the registry row.
        for k in a.keys():
            kl = k.lower()
            self.assertNotIn("token", kl)
            self.assertNotIn("secret", kl)
            self.assertFalse(kl.endswith("key"), f"key-like field: {k}")


class ReadOauthMetadataHelperTest(TestCase):
    """todo#265: unit tests for the read_oauth_metadata() helper.

    The helper lives in the canonical agent_meta.py shipped from
    ``.dotfiles/src/.scitex/orochi/scripts/agent_meta.py`` (see PR
    body for dotfiles sync notes). This test imports it directly
    from that path so the scitex-orochi hub test suite guards the
    token-leak regression even though the helper lives upstream.
    """

    DOTFILES_AGENT_META = (
        "/Users/ywatanabe/.dotfiles/src/.scitex/orochi/scripts/agent_meta.py"
    )

    def _import_helper(self):
        import importlib.util
        import os

        if not os.path.isfile(self.DOTFILES_AGENT_META):
            self.skipTest("dotfiles agent_meta.py not present on this host")
        spec = importlib.util.spec_from_file_location(
            "agent_meta_under_test", self.DOTFILES_AGENT_META
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod

    def test_missing_file_returns_empty(self):
        mod = self._import_helper()
        from pathlib import Path
        result = mod.read_oauth_metadata(Path("/nonexistent/.claude.json"))
        self.assertEqual(result, {})

    def test_all_nine_keys_extracted(self):
        import tempfile
        from pathlib import Path
        mod = self._import_helper()
        doc = {
            "hasAvailableSubscription": True,
            "cachedExtraUsageDisabledReason": "out_of_credits",
            "oauthAccount": {
                "accountUuid": "uuid-abc",
                "emailAddress": "alice@example.org",
                "organizationUuid": "org-uuid",
                "organizationName": "Acme",
                "hasExtraUsageEnabled": False,
                "billingType": "subscription",
                "accountCreatedAt": "2024-01-01",
                "subscriptionCreatedAt": "2025-01-01T00:00:00Z",
                "displayName": "Alice",
                "organizationRole": "admin",
                "workspaceRole": "member",
            },
            # Hostile fields — must not appear in output.
            "accessToken": "sk-ant-oat01-should-not-leak",
            "refreshToken": "sk-ant-ort01-should-not-leak",
            "claudeAiOauth": {"accessToken": "sk-ant-oat01-nested-leak"},
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(doc, f)
            path = Path(f.name)
        try:
            result = mod.read_oauth_metadata(path)
            expected_keys = {
                "oauth_email",
                "oauth_org_name",
                "oauth_account_uuid",
                "oauth_display_name",
                "billing_type",
                "has_available_subscription",
                "usage_disabled_reason",
                "has_extra_usage_enabled",
                "subscription_created_at",
            }
            self.assertEqual(set(result.keys()), expected_keys)
            self.assertEqual(result["oauth_email"], "alice@example.org")
            self.assertEqual(result["oauth_org_name"], "Acme")
            self.assertEqual(result["oauth_account_uuid"], "uuid-abc")
            self.assertEqual(result["oauth_display_name"], "Alice")
            self.assertEqual(result["billing_type"], "subscription")
            self.assertEqual(result["has_available_subscription"], True)
            self.assertEqual(result["usage_disabled_reason"], "out_of_credits")
            self.assertEqual(result["has_extra_usage_enabled"], False)
            self.assertEqual(
                result["subscription_created_at"], "2025-01-01T00:00:00Z"
            )
        finally:
            path.unlink()

    def test_token_leak_regression(self):
        """CRITICAL: hostile top-level fields must never appear in output.

        This is the primary security invariant for todo#265. If a
        future edit blacklist-converts the extractor, or adds a new
        whitelist key, this test catches leakage of any substring
        that looks like a Claude Code token/credential.
        """
        import tempfile
        from pathlib import Path
        mod = self._import_helper()
        hostile = {
            "oauthAccount": {
                "emailAddress": "eve@example.org",
                # Hostile nested field — still must not leak.
                "accessToken": "sk-ant-oat01-nested-should-not-leak",
            },
            "accessToken": "sk-ant-oat01-top-should-not-leak",
            "refreshToken": "sk-ant-ort01-top-should-not-leak",
            "apiKey": "sk-ant-api03-top-should-not-leak",
            "bearer": "Bearer should-not-leak",
            "credentials": {"apiKey": "sk-ant-api03-inner-should-not-leak"},
            "claudeAiOauth": {
                "accessToken": "sk-ant-oat01-claudeai-should-not-leak",
                "refreshToken": "sk-ant-ort01-claudeai-should-not-leak",
            },
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(hostile, f)
            path = Path(f.name)
        try:
            result = mod.read_oauth_metadata(path)
            # Whitelist: no key name should contain token/secret/key.
            for k in result.keys():
                kl = k.lower()
                self.assertNotIn("token", kl)
                self.assertNotIn("secret", kl)
                # "key" substring is too broad (would trip "oauth_email"
                # if we were sloppy); use endswith instead.
                self.assertFalse(
                    kl.endswith("key"), f"forbidden key-like field: {k}"
                )
            # And no value should contain the leaked substrings.
            flat = json.dumps(result).lower()
            forbidden_substrings = (
                "sk-ant-oat01",
                "sk-ant-ort01",
                "sk-ant-api03",
                "should-not-leak",
                "bearer",
            )
            for s in forbidden_substrings:
                self.assertNotIn(
                    s, flat, f"token material {s!r} leaked into output"
                )
        finally:
            path.unlink()


class GroupMentionExpansionTest(TestCase):
    """Regression guard for @heads/@healers/@mambas/@all/@agents expansion.

    The frontend chip renderer in hub/static/hub/chat.js hard-codes the
    same five group tokens as the hub-side GROUP_PATTERNS dict in
    hub/consumers.py (introduced in 526c490). If either side drifts the
    user will see a chip that the backend refuses to expand (or vice
    versa). This test asserts both sides still agree — todo#421.
    """

    #: Must match MENTION_GROUP_TOKENS in hub/static/hub/chat.js and the
    #: GROUP_PATTERNS dict in hub/consumers.py._maybe_mention_reply.
    EXPECTED_TOKENS = {"heads", "healers", "mambas", "all", "agents"}

    def test_consumers_group_patterns_has_expected_tokens(self):
        """consumers.py still declares all five group tokens."""
        from pathlib import Path

        src = (
            Path(__file__).resolve().parent / "consumers.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "GROUP_PATTERNS = {",
            src,
            "consumers.py lost the GROUP_PATTERNS dict (526c490 regression)",
        )
        for token in self.EXPECTED_TOKENS:
            self.assertIn(
                f'"{token}"',
                src,
                f"GROUP_PATTERNS missing @{token} token",
            )

    def test_frontend_chat_js_has_matching_group_tokens(self):
        """chat.js MENTION_GROUP_TOKENS agrees with backend GROUP_PATTERNS."""
        from pathlib import Path

        src = (
            Path(__file__).resolve().parent
            / "static"
            / "hub"
            / "chat.js"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "MENTION_GROUP_TOKENS",
            src,
            "chat.js missing MENTION_GROUP_TOKENS (todo#421)",
        )
        for token in self.EXPECTED_TOKENS:
            self.assertIn(
                f"{token}:",
                src,
                f"chat.js MENTION_GROUP_TOKENS missing @{token}",
            )

    def test_group_expansion_algorithm(self):
        """Pure-Python replication of the consumer's expansion step.

        Guards the algorithm shape (startswith rules + dedupe-preserving
        order) without requiring an async consumer harness.
        """
        GROUP_PATTERNS = {
            "heads": lambda n: n.startswith("head-"),
            "healers": lambda n: n.startswith("mamba-healer"),
            "mambas": lambda n: n.startswith("mamba-"),
            "all": lambda n: True,
            "agents": lambda n: True,
        }
        all_names = [
            "head-mba",
            "head-spartan",
            "mamba-healer-mba",
            "mamba-todo-manager",
            "ywata-note-win",
        ]

        def expand(mentioned):
            out: list[str] = []
            for tok in mentioned:
                if tok in GROUP_PATTERNS:
                    out.extend(
                        n for n in all_names if GROUP_PATTERNS[tok](n)
                    )
                else:
                    out.append(tok)
            return list(dict.fromkeys(out))

        self.assertEqual(
            expand(["heads"]),
            ["head-mba", "head-spartan"],
        )
        self.assertEqual(
            expand(["healers"]),
            ["mamba-healer-mba"],
        )
        self.assertEqual(
            expand(["mambas"]),
            ["mamba-healer-mba", "mamba-todo-manager"],
        )
        self.assertEqual(
            expand(["all"]),
            all_names,
        )
        # Dedupe: @heads + head-mba should not double-fire head-mba.
        self.assertEqual(
            expand(["heads", "head-mba"]),
            ["head-mba", "head-spartan"],
        )
        # Unknown tokens pass through unchanged.
        self.assertEqual(
            expand(["not-a-group", "heads"]),
            ["not-a-group", "head-mba", "head-spartan"],
        )
