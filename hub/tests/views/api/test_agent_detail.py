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


class AgentDetailApiTest(TestCase):
    """todo#420: /api/agents/<name>/detail/ — per-agent single-screen view.

    Pins the response shape the Agents tab sub-tab depends on (see
    ``hub/static/hub/agents-tab.js::_renderAgentDetail``) and verifies
    server-side secret redaction of ``pane_text`` before it leaves the
    hub. The endpoint is authenticated via workspace token so it can
    be polled both from the dashboard and from ``agent_meta.py`` without
    a browser session.
    """

    def setUp(self):
        self.client = Client()
        self.ws = Workspace.objects.create(name="detail-ws")
        self.token = WorkspaceToken.objects.create(
            workspace=self.ws, label="detail-test"
        )
        # Wipe the in-memory registry so state does not bleed across
        # tests — the registry is a module-level dict.
        from hub.registry import _agents as _reg_agents

        _reg_agents.clear()

    def _register(self, **overrides):
        from hub.registry import register_agent, set_orochi_current_task

        orochi_current_task = overrides.pop("orochi_current_task", "todo#420")
        info = {
            "agent_id": "alpha",
            "orochi_machine": "MBA",
            "role": "head",
            "model": "claude-opus-4-7",
            "channels": ["#general", "#agent"],
            "orochi_pane_tail_block": "line1\nline2\n",
            "orochi_claude_md": "# CLAUDE.md\n",
            "orochi_mcp_servers": ["scitex-orochi"],
        }
        info.update(overrides)
        register_agent(name="alpha", workspace_id=self.ws.id, info=info)
        if orochi_current_task:
            set_orochi_current_task("alpha", orochi_current_task)

    def _get(self, name="alpha"):
        return self.client.get(
            f"/api/agents/{name}/detail/",
            data={"token": self.token.token},
        )

    def test_returns_expected_shape(self):
        self._register()
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # Canonical fields the frontend pins.
        for key in (
            "name",
            "role",
            "orochi_machine",
            "model",
            "uptime_seconds",
            "registered_at",
            "last_action_ts",
            "last_heartbeat",
            "liveness",
            "orochi_claude_md",
            "pane_text",
            "pane_text_source",
            "channel_subs",
            "orochi_mcp_servers",
            "orochi_current_task",
            "orochi_context_pct",
            "pid",
            "orochi_subagents",
            "health",
        ):
            self.assertIn(key, data, f"missing key: {key}")
        self.assertEqual(data["name"], "alpha")
        self.assertEqual(data["role"], "head")
        self.assertEqual(data["orochi_machine"], "MBA")
        self.assertEqual(data["orochi_current_task"], "todo#420")
        self.assertEqual(data["pane_text_source"], "cached")
        self.assertIn("line1", data["pane_text"])
        self.assertEqual(sorted(data["channel_subs"]), ["#agent", "#general"])
        self.assertIn("scitex-orochi", data["orochi_mcp_servers"])

    def test_unavailable_pane_source_when_no_capture(self):
        self._register(orochi_pane_tail_block="", orochi_pane_tail="")
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["pane_text_source"], "unavailable")
        self.assertEqual(data["pane_text"], "")

    def test_missing_agent_returns_404(self):
        self._register()
        resp = self._get(name="bravo")
        self.assertEqual(resp.status_code, 404)

    def test_auth_required(self):
        self._register()
        resp = self.client.get("/api/agents/alpha/detail/")
        self.assertEqual(resp.status_code, 401)

    def test_invalid_token_rejected(self):
        self._register()
        resp = self.client.get(
            "/api/agents/alpha/detail/",
            data={"token": "wks_invalid"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_pane_text_redacts_secrets(self):
        """sk-ant / ghp / JWT / bearer / credentials-file patterns
        must never leak through ``pane_text``."""
        leak = "\n".join(
            [
                "normal line 1",
                "ANTHROPIC_API_KEY=sk-ant-oat01-ABCDEFGHIJKLMNOPQRST",
                "gh token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
                "id_token: eyJabcdefghij.eyJklmnopqrst.signatureXYZ123",
                "Authorization: Bearer sk-oat-ABCDEFGHIJKLMNOPQR",
                "cat ~/.credentials.json",
                "normal line 2",
            ]
        )
        self._register(orochi_pane_tail_block=leak)
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        pane = data["pane_text"]
        for forbidden in (
            "sk-ant-oat01-ABCDEFGHIJKLMNOPQRST",
            "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
            "eyJabcdefghij.eyJklmnopqrst.signatureXYZ123",
            ".credentials.json",
        ):
            self.assertNotIn(
                forbidden,
                pane,
                f"unredacted secret {forbidden!r} leaked into pane_text",
            )
        # The non-secret content survives so the UI is still useful.
        self.assertIn("normal line 1", pane)
        self.assertIn("normal line 2", pane)
        self.assertIn("[REDACTED]", pane)

    def test_redact_secrets_helper_direct(self):
        """Unit-level pin on :func:`redact_secrets` itself, independent
        of the HTTP layer — cheap regression guard."""
        from hub.views.agent_detail import redact_secrets

        src = "prefix sk-ant-api03-ABCDEFGHIJKLMNOPQRST suffix"
        out = redact_secrets(src)
        self.assertNotIn("sk-ant-api03-ABCDEFGHIJKLMNOPQRST", out)
        self.assertIn("[REDACTED]", out)
        self.assertEqual(redact_secrets(""), "")

    def test_orochi_hostname_canonical_exposed(self):
        """todo#55: detail endpoint must forward the canonical FQDN
        pushed by the heartbeat (PR #215/#216). Empty string when the
        client never pushed one."""
        self._register(orochi_hostname_canonical="Yusukes-MacBook-Air.local")
        data = self._get().json()
        self.assertEqual(data["orochi_hostname_canonical"], "Yusukes-MacBook-Air.local")
        # Default path: field present but empty when client didn't push.
        from hub.registry import _agents as _reg_agents

        _reg_agents.clear()
        self._register()
        data2 = self._get().json()
        self.assertIn("orochi_hostname_canonical", data2)
        self.assertEqual(data2["orochi_hostname_canonical"], "")

    def test_pane_text_full_exposed(self):
        """todo#47: detail endpoint must forward the ~500-line
        orochi_pane_tail_full scrollback when the agent pushes it; empty
        string when the agent hasn't updated its agent_meta.py."""
        # New agent with orochi_pane_tail_full populated.
        big_pane = "\n".join(f"line-{i}" for i in range(200))
        self._register(orochi_pane_tail_full=big_pane)
        data = self._get().json()
        self.assertIn("pane_text_full", data)
        # Content flows through redact_secrets (no secrets in this fixture).
        self.assertIn("line-199", data["pane_text_full"])

        # Old agent without orochi_pane_tail_full: field present, empty.
        from hub.registry import _agents as _reg_agents

        _reg_agents.clear()
        self._register()
        data2 = self._get().json()
        self.assertIn("pane_text_full", data2)
        self.assertEqual(data2["pane_text_full"], "")

    def test_ping_pong_fields_exposed(self):
        """todo#46: detail endpoint must expose last_pong_ts / last_rtt_ms
        once update_pong has been called, and must always include the
        keys (as None) when no pong has been received yet."""
        self._register()
        # Fresh registration: fields present but null.
        data = self._get().json()
        self.assertIn("last_pong_ts", data)
        self.assertIn("last_rtt_ms", data)
        self.assertIsNone(data["last_pong_ts"])
        self.assertIsNone(data["last_rtt_ms"])

        # After a pong: last_rtt_ms is the float we recorded, last_pong_ts
        # is an ISO8601 string close to "now".
        from hub.registry import update_pong

        update_pong("alpha", 42.5)
        data2 = self._get().json()
        self.assertAlmostEqual(data2["last_rtt_ms"], 42.5, places=3)
        self.assertIsNotNone(data2["last_pong_ts"])
        self.assertIn("T", data2["last_pong_ts"])  # ISO8601 marker

    def test_event_log_shortcuts_projected(self):
        """The hook-event / action_store shortcuts the frontend reads
        for the Last tool / Last MCP / Last action rows must always be
        present in the detail payload — empty strings when the agent
        hasn't produced any events yet, NOT missing keys."""
        self._register()
        data = self._get().json()
        for key in (
            "sac_hooks_last_tool_at",
            "sac_hooks_last_tool_name",
            "sac_hooks_last_mcp_tool_at",
            "sac_hooks_last_mcp_tool_name",
            "sac_hooks_last_action_at",
            "sac_hooks_last_action_name",
            "sac_hooks_last_action_outcome",
            "sac_hooks_recent_tools",
            "sac_hooks_tool_counts",
            "action_counts",
        ):
            self.assertIn(key, data, f"missing key: {key}")

    def test_event_log_shortcuts_forwarded_when_registered(self):
        """When the heartbeat includes sac_hooks_last_tool_at / sac_hooks_last_tool_name,
        the detail endpoint forwards them verbatim."""
        self._register(
            sac_hooks_last_tool_at="2026-04-18T11:00:00+00:00",
            last_tool_name="Bash",
            sac_hooks_last_mcp_tool_at="2026-04-18T11:00:05+00:00",
            last_mcp_tool_name="mcp__scitex-orochi__send_message",
            sac_hooks_last_action_at="2026-04-18T11:00:10+00:00",
            last_action_name="nonce_probe",
            sac_hooks_last_action_outcome="SUCCESS",
        )
        data = self._get().json()
        self.assertEqual(data["sac_hooks_last_tool_at"], "2026-04-18T11:00:00+00:00")
        self.assertEqual(data["sac_hooks_last_tool_name"], "Bash")
        self.assertEqual(data["sac_hooks_last_mcp_tool_name"], "mcp__scitex-orochi__send_message")
        self.assertEqual(data["sac_hooks_last_action_name"], "nonce_probe")
        self.assertEqual(data["sac_hooks_last_action_outcome"], "SUCCESS")
