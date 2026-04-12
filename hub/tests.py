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
