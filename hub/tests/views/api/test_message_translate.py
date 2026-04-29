"""Tests for POST /api/messages/<id>/translate/ (todo#409 Phase 1)."""

import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import Client, TestCase

from hub.models import Channel, Message, Workspace, WorkspaceMember


def _ws_host(ws):
    return f"{ws.name}.lvh.me"


class MessageTranslateTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="tester", password="pass")
        self.ws = Workspace.objects.create(name="tr-ws")
        WorkspaceMember.objects.create(workspace=self.ws, user=self.user, role="member")
        self.ch = Channel.objects.create(workspace=self.ws, name="#general")
        self.msg = Message.objects.create(
            workspace=self.ws,
            channel=self.ch,
            sender="tester",
            content="こんにちは世界",
        )
        self.client.login(username="tester", password="pass")

    def _post(self, msg_id, body=None):
        return self.client.post(
            f"/api/messages/{msg_id}/translate/",
            data=json.dumps(body or {"target_lang": "en"}),
            content_type="application/json",
            HTTP_HOST=_ws_host(self.ws),
        )

    def test_no_api_key_returns_503(self):
        with patch.dict("os.environ", {}, clear=True):
            import importlib

            import hub.views.api._translate as m
            importlib.reload(m)
        resp = self._post(self.msg.id)
        self.assertEqual(resp.status_code, 503)

    def test_requires_auth(self):
        self.client.logout()
        resp = self._post(self.msg.id)
        self.assertEqual(resp.status_code, 401)

    def test_404_for_missing_message(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "content": [{"text": "Hello world"}]
        }
        with patch("hub.views.api._translate.httpx.post", return_value=mock_resp):
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
                resp = self._post(99999)
        self.assertEqual(resp.status_code, 404)

    def test_successful_translation(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "content": [{"text": "Hello world"}]
        }
        with patch("hub.views.api._translate.httpx.post", return_value=mock_resp):
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
                resp = self._post(self.msg.id, {"target_lang": "en"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["translated_text"], "Hello world")
        self.assertEqual(data["target_lang"], "en")
        self.assertEqual(data["original_text"], "こんにちは世界")

    def test_api_error_returns_502(self):
        import httpx as _httpx
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        exc = _httpx.HTTPStatusError("rate limit", request=MagicMock(), response=mock_resp)
        with patch("hub.views.api._translate.httpx.post", side_effect=exc):
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
                resp = self._post(self.msg.id)
        self.assertEqual(resp.status_code, 502)
