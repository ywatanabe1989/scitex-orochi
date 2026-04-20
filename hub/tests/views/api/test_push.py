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
        self.assertFalse(PushSubscription.objects.filter(pk=self.sub_bob.pk).exists())

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
