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

    def test_register_persists_orochi_subagent_count(self):
        """Heartbeat's ``orochi_subagent_count`` field reaches hub.registry and
        is exposed via get_agents() unchanged.

        Pinned here because the sidecar parses the tmux pane for
        ``N local agent(s) running`` and relies on the hub treating the
        field as authoritative (not silently overwriting it with the
        length of the ``subagents`` list, which is empty on the Python
        --push path)."""
        from hub.registry import _agents as _reg_agents
        from hub.registry import get_agents

        _reg_agents.clear()
        for count in (0, 1, 3, 7):
            resp = self._post(
                {
                    "token": self.token.token,
                    "name": f"sub-count-{count}",
                    "orochi_subagent_count": count,
                }
            )
            self.assertEqual(resp.status_code, 200)
            a = [
                x
                for x in get_agents(workspace_id=self.ws.id)
                if x["name"] == f"sub-count-{count}"
            ][0]
            self.assertEqual(a["orochi_subagent_count"], count)

    def test_register_persists_sac_status(self):
        """lead msg#16005: the full ``scitex-agent-container status
        --terse --json`` dict attached as ``sac_status`` is stored
        verbatim and surfaced on ``/api/agents/``.

        This pins the hub-side half of the pivot — every field the
        pusher forwards reaches the dashboard payload without a
        per-field allowlist. New fields in sac's terse projection
        (``context_management.percent``, ``orochi_pane_state``,
        ``orochi_current_tool``, ...) should therefore appear on
        ``get_agents()[i]["sac_status"][<field>]`` the moment the
        pusher sends them.
        """
        from hub.registry import _agents as _reg_agents
        from hub.registry import get_agents

        _reg_agents.clear()
        sac = {
            "agent": "sac-full",
            "state": "running",
            "context_management.percent": 42.0,
            "context_management.strategy": "compact",
            "pids.claude_code": 54321,
            "health.ok": True,
            "tmux_alive": True,
        }
        resp = self._post(
            {
                "token": self.token.token,
                "name": "sac-full",
                "sac_status": sac,
            }
        )
        self.assertEqual(resp.status_code, 200)
        a = [x for x in get_agents(workspace_id=self.ws.id) if x["name"] == "sac-full"][
            0
        ]
        self.assertEqual(a["sac_status"], sac)
        # Nested-key access survives round-trip (the whole point of
        # the pivot).
        self.assertEqual(a["sac_status"]["context_management.percent"], 42.0)
        self.assertTrue(a["sac_status"]["health.ok"])

    def test_register_preserves_sac_status_when_absent(self):
        """Two heartbeats in a row: first with sac_status, second
        without. The second must NOT wipe the stored dict — the
        prev-preserve rule in ``register_agent`` is load-bearing so a
        transient ``sac status`` CLI failure doesn't blank the field
        every 30s.
        """
        from hub.registry import _agents as _reg_agents
        from hub.registry import get_agents

        _reg_agents.clear()
        sac = {"agent": "sac-preserve", "state": "running"}
        # First push populates the field.
        self._post(
            {
                "token": self.token.token,
                "name": "sac-preserve",
                "sac_status": sac,
            }
        )
        # Second push omits the field entirely.
        self._post({"token": self.token.token, "name": "sac-preserve"})
        a = [
            x
            for x in get_agents(workspace_id=self.ws.id)
            if x["name"] == "sac-preserve"
        ][0]
        self.assertEqual(a["sac_status"], sac)

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


class AgentRegisterAuthMatrixTest(TestCase):
    """v02 audit §1 follow-up: ``/api/agents/register/`` accepts the
    workspace token via JSON body OR ``Authorization: Bearer <token>``
    header, and rejects ``?token=`` (logs/Referer leak path).

    Pins the three auth modes + the explicit-reject case so the security
    fix can't silently regress on the next refactor of
    ``hub/views/api/_agents_register.py``.
    """

    def setUp(self):
        self.client = Client()
        self.ws = Workspace.objects.create(name="auth-matrix-ws")
        self.token = WorkspaceToken.objects.create(
            workspace=self.ws, label="auth-matrix"
        )

    def _post(self, payload, *, headers=None, query=""):
        return self.client.post(
            f"/api/agents/register/{query}",
            data=json.dumps(payload),
            content_type="application/json",
            **(headers or {}),
        )

    def test_body_token_accepted(self):
        resp = self._post({"token": self.token.token, "name": "body-agent"})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["status"], "ok")

    def test_authorization_bearer_accepted(self):
        resp = self._post(
            {"name": "bearer-agent"},
            headers={"HTTP_AUTHORIZATION": f"Bearer {self.token.token}"},
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["status"], "ok")

    def test_authorization_lowercase_accepted(self):
        # The check is case-insensitive on the scheme keyword.
        resp = self._post(
            {"name": "bearer-lower"},
            headers={"HTTP_AUTHORIZATION": f"bearer {self.token.token}"},
        )
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_query_string_token_rejected_with_400(self):
        # Even when the body has a valid token, a query-string token
        # is a config-bug signal — fail loudly so misconfigured agents
        # don't silently leak via webserver access logs.
        resp = self._post(
            {"token": self.token.token, "name": "no-query"},
            query=f"?token={self.token.token}",
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        body = resp.json()
        self.assertIn("query string", body["error"])

    def test_missing_token_returns_401(self):
        resp = self._post({"name": "no-auth"})
        self.assertEqual(resp.status_code, 401, resp.content)
        self.assertEqual(resp.json()["error"], "token required")

    def test_invalid_bearer_returns_401(self):
        resp = self._post(
            {"name": "bad-bearer"},
            headers={"HTTP_AUTHORIZATION": "Bearer not_a_real_token"},
        )
        self.assertEqual(resp.status_code, 401, resp.content)
        self.assertEqual(resp.json()["error"], "invalid token")
