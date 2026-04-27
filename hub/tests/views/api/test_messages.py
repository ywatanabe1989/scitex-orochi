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

    def test_api_media_surfaces_old_attachments_past_noisy_metadata(self):
        """Regression: /api/media/ used to scan the newest 400 messages
        with any non-empty metadata. On a busy workspace, reactions /
        reply metadata crowded out the window and attachments uploaded
        further back never showed up in the Files tab. The query now
        filters for ``metadata__has_key="attachments"`` so the limit
        applies to attachment-bearing messages specifically.
        """
        # Simulate the busy-workspace pattern: many newer messages with
        # non-empty metadata that do NOT carry attachments. Need more
        # than the old code's 400-row overshoot (limit=200 × 2) so the
        # attachment falls outside the scan window in the broken
        # version.
        Message.objects.bulk_create(
            [
                Message(
                    workspace=self.ws,
                    channel=self.ch,
                    sender=f"bot-{i}",
                    content=f"noise-{i}",
                    metadata={"reactions": [{"emoji": "👍"}]},
                )
                for i in range(450)
            ]
        )
        # …and one OLDER message that actually has an attachment. Newer
        # reaction-only messages should not evict it from the result.
        import datetime as _dt

        old_att_msg = Message.objects.create(
            workspace=self.ws,
            channel=self.ch,
            sender="ywatanabe",
            content="has attachment",
            metadata={
                "attachments": [
                    {
                        "url": "/media/2026-04/abc.pdf",
                        "filename": "abc.pdf",
                        "mime_type": "application/pdf",
                        "size": 1234,
                    }
                ]
            },
        )
        Message.objects.filter(pk=old_att_msg.pk).update(
            ts=_dt.datetime(2026, 4, 1, 0, 0, tzinfo=_dt.timezone.utc)
        )
        # Hit the workspace subdomain (api-ws.lvh.me) so
        # WorkspaceSubdomainMiddleware dispatches to hub.urls_workspace.
        resp = self.client.get("/api/media/", HTTP_HOST="api-ws.lvh.me")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        filenames = [item["filename"] for item in data]
        self.assertIn(
            "abc.pdf",
            filenames,
            f"older attachment was evicted by newer reaction-only "
            f"messages; got {filenames!r}",
        )


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
