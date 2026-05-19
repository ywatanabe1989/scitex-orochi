"""Tests for POST /api/inbound-email/ (#81).

Covers:
1. Routing logic (from-address, subject patterns, explicit override).
2. Token auth (missing, invalid, valid).
3. Request body validation.
4. Message persistence + response shape.
5. Broadcast attempted (but channel layer may be absent in test env).
"""

import json

from django.test import Client, TestCase

from hub.models import Channel, Message, Workspace, WorkspaceToken
from hub.views.api._inbound_email import _format_email_message, route_email


class RouteEmailTest(TestCase):
    """Pure unit tests for route_email() — no DB, no HTTP."""

    def test_github_from_address_routes_to_github(self):
        self.assertEqual(route_email("bot@github.com", "PR opened"), "#github")

    def test_noreply_github_routes_to_github(self):
        self.assertEqual(route_email("noreply@github.com", "Issue comment"), "#github")

    def test_ci_failure_subject_routes_to_escalation(self):
        self.assertEqual(route_email("ci@example.com", "[CI] failure detected"), "#escalation")

    def test_failure_keyword_routes_to_escalation(self):
        self.assertEqual(route_email("build@example.com", "Build failed"), "#escalation")

    def test_alert_subject_routes_to_escalation(self):
        self.assertEqual(route_email("monitor@example.com", "alert: disk 95%"), "#escalation")

    def test_github_in_subject_routes_to_github(self):
        self.assertEqual(route_email("unknown@example.com", "Your github PR"), "#github")

    def test_unknown_routes_to_general(self):
        self.assertEqual(route_email("friend@example.com", "Hello there"), "#general")

    def test_explicit_override_wins_over_from(self):
        self.assertEqual(route_email("bot@github.com", "PR", routing_channel="#research"), "#research")

    def test_override_adds_hash_prefix_if_missing(self):
        result = route_email("a@b.com", "hi", routing_channel="research")
        self.assertEqual(result, "#research")

    def test_empty_from_and_subject_falls_through_to_general(self):
        self.assertEqual(route_email("", ""), "#general")


class FormatEmailMessageTest(TestCase):
    def test_full_message(self):
        text = _format_email_message("user@example.com", "Test subject", "Body text here")
        self.assertIn("Test subject", text)
        self.assertIn("user@example.com", text)
        self.assertIn("Body text here", text)

    def test_truncation_at_2000_chars(self):
        long_body = "x" * 3000
        text = _format_email_message("a@b.com", "s", long_body)
        self.assertIn("truncated", text)

    def test_empty_fields_no_crash(self):
        text = _format_email_message("", "", "")
        self.assertIsInstance(text, str)


class InboundEmailApiTest(TestCase):
    def setUp(self):
        self.ws = Workspace.objects.create(name="email-test-ws")
        self.token = WorkspaceToken.objects.create(workspace=self.ws, label="email-hook")
        self.client = Client()

    def _post(self, data: dict) -> object:
        return self.client.post(
            "/api/inbound-email/",
            data=json.dumps(data),
            content_type="application/json",
        )

    def test_missing_token_returns_401(self):
        resp = self._post({"from": "a@b.com", "subject": "hi", "body_text": "hello"})
        self.assertEqual(resp.status_code, 401)

    def test_invalid_token_returns_401(self):
        resp = self._post({"token": "bad-token-xyz", "from": "a@b.com", "subject": "hi"})
        self.assertEqual(resp.status_code, 401)

    def test_empty_body_fields_returns_400(self):
        resp = self._post({"token": self.token.token})
        self.assertEqual(resp.status_code, 400)

    def test_valid_request_returns_201(self):
        resp = self._post({
            "token": self.token.token,
            "from": "bot@github.com",
            "subject": "PR opened",
            "body_text": "A new pull request was opened.",
        })
        self.assertEqual(resp.status_code, 201)
        body = json.loads(resp.content)
        self.assertTrue(body["ok"])
        self.assertIn("message_id", body)
        self.assertIn("channel", body)

    def test_github_email_routed_to_github_channel(self):
        resp = self._post({
            "token": self.token.token,
            "from": "noreply@github.com",
            "subject": "Issue comment",
            "body_text": "Someone commented.",
        })
        self.assertEqual(resp.status_code, 201)
        body = json.loads(resp.content)
        self.assertEqual(body["channel"], "#github")

    def test_explicit_routing_channel_override(self):
        resp = self._post({
            "token": self.token.token,
            "from": "bot@github.com",
            "subject": "PR merged",
            "body_text": "Merged.",
            "routing_channel": "#research",
        })
        self.assertEqual(resp.status_code, 201)
        body = json.loads(resp.content)
        self.assertEqual(body["channel"], "#research")

    def test_message_persisted_to_db(self):
        resp = self._post({
            "token": self.token.token,
            "from": "ci@example.com",
            "subject": "Build result",
            "body_text": "Success.",
        })
        self.assertEqual(resp.status_code, 201)
        msg_id = json.loads(resp.content)["message_id"]
        msg = Message.objects.get(id=msg_id)
        self.assertEqual(msg.sender, "inbound-email")
        self.assertIn("Build result", msg.content)

    def test_channel_created_if_not_exists(self):
        self._post({
            "token": self.token.token,
            "from": "a@b.com",
            "subject": "hi",
            "body_text": "hello",
            "routing_channel": "#new-channel",
        })
        self.assertTrue(Channel.objects.filter(workspace=self.ws, name="#new-channel").exists())

    def test_form_encoded_body_also_works(self):
        resp = self.client.post(
            "/api/inbound-email/",
            data={
                "token": self.token.token,
                "from": "a@b.com",
                "subject": "test",
                "body_text": "hello",
            },
        )
        self.assertEqual(resp.status_code, 201)

    def test_only_from_field_accepted(self):
        resp = self._post({
            "token": self.token.token,
            "from": "a@b.com",
        })
        self.assertEqual(resp.status_code, 201)
