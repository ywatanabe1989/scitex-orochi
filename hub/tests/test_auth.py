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
