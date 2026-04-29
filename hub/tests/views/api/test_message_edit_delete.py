"""Tests for PATCH/DELETE /api/messages/<id>/ on workspace subdomains.

Covers todo#403 (delete own post) and todo#404 (edit own post).
"""

import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import Client, TestCase

from hub.models import Channel, Message, Workspace, WorkspaceMember


def _ws_host(ws):
    return f"{ws.name}.lvh.me"


def _noop_ws_broadcast():
    """Return a pair of patches that make WS broadcast a no-op."""
    layer_mock = MagicMock()
    layer_mock.group_send = MagicMock()
    return (
        patch("hub.views.api._reactions.get_channel_layer", return_value=layer_mock),
        patch("hub.views.api._reactions.async_to_sync", side_effect=lambda f: lambda *a, **kw: None),
    )


class MessageEditTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(username="owner", password="pass")
        self.other = User.objects.create_user(username="other", password="pass")
        self.ws = Workspace.objects.create(name="edit-ws")
        WorkspaceMember.objects.create(workspace=self.ws, user=self.owner, role="member")
        WorkspaceMember.objects.create(workspace=self.ws, user=self.other, role="member")
        self.ch = Channel.objects.create(workspace=self.ws, name="#general")
        self.msg = Message.objects.create(
            workspace=self.ws,
            channel=self.ch,
            sender="owner",
            content="original text",
        )

    def _patch(self, msg_id, body, user="owner"):
        self.client.login(username=user, password="pass")
        return self.client.patch(
            f"/api/messages/{msg_id}/",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_HOST=_ws_host(self.ws),
        )

    def test_edit_own_message_succeeds(self):
        p_layer, p_sync = _noop_ws_broadcast()
        with p_layer, p_sync:
            resp = self._patch(self.msg.id, {"text": "updated text"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["edited"])
        self.msg.refresh_from_db()
        self.assertEqual(self.msg.content, "updated text")
        self.assertTrue(self.msg.edited)
        self.assertIsNotNone(self.msg.edited_at)

    def test_edit_other_message_forbidden(self):
        p_layer, p_sync = _noop_ws_broadcast()
        with p_layer, p_sync:
            resp = self._patch(self.msg.id, {"text": "hacked"}, user="other")
        self.assertEqual(resp.status_code, 403)
        self.msg.refresh_from_db()
        self.assertEqual(self.msg.content, "original text")

    def test_edit_requires_auth(self):
        resp = self.client.patch(
            f"/api/messages/{self.msg.id}/",
            data=json.dumps({"text": "x"}),
            content_type="application/json",
            HTTP_HOST=_ws_host(self.ws),
        )
        self.assertEqual(resp.status_code, 401)

    def test_edit_empty_text_rejected(self):
        p_layer, p_sync = _noop_ws_broadcast()
        with p_layer, p_sync:
            resp = self._patch(self.msg.id, {})
        self.assertEqual(resp.status_code, 400)

    def test_edit_nonexistent_message_404(self):
        p_layer, p_sync = _noop_ws_broadcast()
        with p_layer, p_sync:
            resp = self._patch(99999, {"text": "x"})
        self.assertEqual(resp.status_code, 404)

    def test_edited_tag_in_history_response(self):
        p_layer, p_sync = _noop_ws_broadcast()
        with p_layer, p_sync:
            self._patch(self.msg.id, {"text": "updated text"})
        self.client.login(username="owner", password="pass")
        resp = self.client.get(
            "/api/history/general/",
            HTTP_HOST=_ws_host(self.ws),
        )
        self.assertEqual(resp.status_code, 200)
        msgs = resp.json()
        found = [m for m in msgs if m["id"] == self.msg.id]
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]["edited"])


class MessageDeleteTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(username="owner", password="pass")
        self.other = User.objects.create_user(username="other", password="pass")
        self.admin_user = User.objects.create_user(username="admin_user", password="pass")
        self.ws = Workspace.objects.create(name="del-ws")
        WorkspaceMember.objects.create(workspace=self.ws, user=self.owner, role="member")
        WorkspaceMember.objects.create(workspace=self.ws, user=self.other, role="member")
        WorkspaceMember.objects.create(workspace=self.ws, user=self.admin_user, role="admin")
        self.ch = Channel.objects.create(workspace=self.ws, name="#general")
        self.msg = Message.objects.create(
            workspace=self.ws,
            channel=self.ch,
            sender="owner",
            content="to be deleted",
        )

    def _delete(self, msg_id, user="owner"):
        self.client.login(username=user, password="pass")
        return self.client.delete(
            f"/api/messages/{msg_id}/",
            HTTP_HOST=_ws_host(self.ws),
        )

    def test_delete_own_message_soft_deletes(self):
        p_layer, p_sync = _noop_ws_broadcast()
        with p_layer, p_sync:
            resp = self._delete(self.msg.id)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["deleted"])
        self.msg.refresh_from_db()
        self.assertIsNotNone(self.msg.deleted_at)

    def test_delete_other_message_forbidden(self):
        p_layer, p_sync = _noop_ws_broadcast()
        with p_layer, p_sync:
            resp = self._delete(self.msg.id, user="other")
        self.assertEqual(resp.status_code, 403)
        self.msg.refresh_from_db()
        self.assertIsNone(self.msg.deleted_at)

    def test_admin_can_delete_any_message(self):
        p_layer, p_sync = _noop_ws_broadcast()
        with p_layer, p_sync:
            resp = self._delete(self.msg.id, user="admin_user")
        self.assertEqual(resp.status_code, 200)
        self.msg.refresh_from_db()
        self.assertIsNotNone(self.msg.deleted_at)

    def test_delete_requires_auth(self):
        resp = self.client.delete(
            f"/api/messages/{self.msg.id}/",
            HTTP_HOST=_ws_host(self.ws),
        )
        self.assertEqual(resp.status_code, 401)

    def test_deleted_message_excluded_from_history(self):
        p_layer, p_sync = _noop_ws_broadcast()
        with p_layer, p_sync:
            self._delete(self.msg.id)
        self.client.login(username="owner", password="pass")
        resp = self.client.get(
            "/api/history/general/",
            HTTP_HOST=_ws_host(self.ws),
        )
        self.assertEqual(resp.status_code, 200)
        msgs = resp.json()
        ids = [m["id"] for m in msgs]
        self.assertNotIn(self.msg.id, ids)
