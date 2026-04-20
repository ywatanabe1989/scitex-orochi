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
        resp = self._post(
            {
                "token": self.token.token,
                "name": "oauth-agent-2",
                "usage_disabled_reason": "out_of_credits",
            }
        )
        self.assertEqual(resp.status_code, 200)
        a = [
            x
            for x in get_agents(workspace_id=self.ws.id)
            if x["name"] == "oauth-agent-2"
        ][0]
        self.assertEqual(a["usage_disabled_reason"], "out_of_credits")

    def test_register_missing_oauth_fields_defaults(self):
        """Legacy agents without oauth fields still register cleanly."""
        from hub.registry import _agents as _reg_agents
        from hub.registry import get_agents

        _reg_agents.clear()
        resp = self._post(
            {
                "token": self.token.token,
                "name": "legacy-agent",
            }
        )
        self.assertEqual(resp.status_code, 200)
        a = [
            x
            for x in get_agents(workspace_id=self.ws.id)
            if x["name"] == "legacy-agent"
        ][0]
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
        resp = self._post(
            {
                "token": self.token.token,
                "name": "leak-test",
                "oauth_email": "bob@example.org",
                # Hostile fields — must NOT end up in the registry.
                "accessToken": "sk-ant-oat01-leaked",
                "refreshToken": "sk-ant-ort01-leaked",
                "apiKey": "sk-ant-api03-leaked",
                "claudeAiOauth": {"accessToken": "sk-ant-oat01-leaked"},
                "credentials": "bearer leaked",
            }
        )
        self.assertEqual(resp.status_code, 200)
        a = [
            x for x in get_agents(workspace_id=self.ws.id) if x["name"] == "leak-test"
        ][0]
        flat = json.dumps(a).lower()
        for forbidden in (
            "sk-ant-oat01-leaked",
            "sk-ant-ort01-leaked",
            "sk-ant-api03-leaked",
            "bearer leaked",
        ):
            self.assertNotIn(
                forbidden,
                flat,
                f"leaked token material {forbidden!r} in registry entry",
            )
        # And no forbidden keys in the registry row.
        for k in a.keys():
            kl = k.lower()
            self.assertNotIn("token", kl)
            self.assertNotIn("secret", kl)
            self.assertFalse(kl.endswith("key"), f"key-like field: {k}")
