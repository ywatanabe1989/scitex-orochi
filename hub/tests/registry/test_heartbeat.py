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


class FunctionalHeartbeatAndHookEventsTest(TestCase):
    """Smoke tests for the functional-heartbeat shortcuts and
    hook-event passthrough landed with the agent-detail upgrade
    (feat(hub): agent-detail upgrades commit).

    Ensures the end-to-end pipe
    ``scitex-agent-container status --json`` ->
    ``scitex-orochi heartbeat-push`` ->
    ``POST /api/agents/register/`` -> registry ->
    ``GET /api/agents/<name>/detail/`` preserves:

      - ``sac_hooks_last_tool_at`` / ``sac_hooks_last_tool_name``  — LLM liveness signal
      - ``sac_hooks_last_mcp_tool_at`` / ``sac_hooks_last_mcp_tool_name`` — MCP sidecar route
      - ``sac_hooks_recent_tools`` / ``sac_hooks_recent_prompts`` / ``sac_hooks_agent_calls`` /
        ``background_tasks`` / ``sac_hooks_tool_counts`` — hook ring-buffer
        views rendered in the per-agent detail panels.
    """

    def setUp(self):
        self.client = Client()
        self.ws = Workspace.objects.create(name="hb-test-ws")
        self.token = WorkspaceToken.objects.create(workspace=self.ws, label="hb-test")
        from hub.registry import _agents as _reg_agents

        _reg_agents.clear()

    def _post(self, payload):
        return self.client.post(
            "/api/agents/register/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def _get_detail(self, name):
        return self.client.get(
            f"/api/agents/{name}/detail/",
            data={"token": self.token.token},
        )

    def _base_payload(self, **overrides):
        payload = {
            "token": self.token.token,
            "name": "hb-agent",
            "machine": "MBA",
            "role": "head",
        }
        payload.update(overrides)
        return payload

    def test_register_persists_last_tool_fields(self):
        from hub.registry import get_agents

        resp = self._post(
            self._base_payload(
                sac_hooks_last_tool_at="2026-04-17T00:00:00+00:00",
                last_tool_name="Edit",
            )
        )
        self.assertEqual(resp.status_code, 200)
        agents = get_agents(workspace_id=self.ws.id)
        match = [a for a in agents if a["name"] == "hb-agent"]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["sac_hooks_last_tool_at"], "2026-04-17T00:00:00+00:00")
        self.assertEqual(match[0]["sac_hooks_last_tool_name"], "Edit")

    def test_register_persists_last_mcp_tool_fields(self):
        from hub.registry import get_agents

        resp = self._post(
            self._base_payload(
                sac_hooks_last_mcp_tool_at="2026-04-17T00:01:00+00:00",
                last_mcp_tool_name="mcp__orochi__send_message",
            )
        )
        self.assertEqual(resp.status_code, 200)
        agents = get_agents(workspace_id=self.ws.id)
        a = next(a for a in agents if a["name"] == "hb-agent")
        self.assertEqual(a["sac_hooks_last_mcp_tool_at"], "2026-04-17T00:01:00+00:00")
        self.assertEqual(a["sac_hooks_last_mcp_tool_name"], "mcp__orochi__send_message")

    def test_register_persists_hook_event_lists(self):
        """sac_hooks_recent_tools / prompts / sac_hooks_agent_calls / background_tasks /
        sac_hooks_tool_counts round-trip into the registry unmodified."""
        from hub.registry import get_agents

        sac_hooks_recent_tools = [
            {"ts": "2026-04-17T00:00:00Z", "tool": "Edit", "input_preview": "/f.py"},
            {"ts": "2026-04-17T00:00:05Z", "tool": "Bash", "input_preview": "pytest"},
        ]
        sac_hooks_recent_prompts = [
            {"ts": "2026-04-17T00:00:00Z", "prompt_preview": "fix the bug"},
        ]
        sac_hooks_agent_calls = [
            {"ts": "2026-04-17T00:00:02Z", "input_preview": "deep-research"},
        ]
        background_tasks = [
            {"ts": "2026-04-17T00:00:03Z", "input_preview": "tail -f log"},
        ]
        sac_hooks_tool_counts = {"Edit": 1, "Bash": 1, "Agent": 1}
        resp = self._post(
            self._base_payload(
                sac_hooks_recent_tools=sac_hooks_recent_tools,
                sac_hooks_recent_prompts=sac_hooks_recent_prompts,
                sac_hooks_agent_calls=sac_hooks_agent_calls,
                background_tasks=background_tasks,
                sac_hooks_tool_counts=sac_hooks_tool_counts,
            )
        )
        self.assertEqual(resp.status_code, 200)
        agents = get_agents(workspace_id=self.ws.id)
        a = next(a for a in agents if a["name"] == "hb-agent")
        self.assertEqual(a["sac_hooks_recent_tools"], sac_hooks_recent_tools)
        self.assertEqual(a["sac_hooks_recent_prompts"], sac_hooks_recent_prompts)
        self.assertEqual(a["sac_hooks_agent_calls"], sac_hooks_agent_calls)
        self.assertEqual(a["background_tasks"], background_tasks)
        self.assertEqual(a["sac_hooks_tool_counts"], sac_hooks_tool_counts)

    def test_detail_api_surfaces_last_tool_fields(self):
        """The four shortcuts must appear in /api/agents/<name>/detail/."""
        self._post(
            self._base_payload(
                sac_hooks_last_tool_at="2026-04-17T01:00:00+00:00",
                last_tool_name="Write",
                sac_hooks_last_mcp_tool_at="2026-04-17T00:59:30+00:00",
                last_mcp_tool_name="mcp__orochi__channel_info",
            )
        )
        resp = self._get_detail("hb-agent")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["sac_hooks_last_tool_at"], "2026-04-17T01:00:00+00:00")
        self.assertEqual(data["sac_hooks_last_tool_name"], "Write")
        self.assertEqual(data["sac_hooks_last_mcp_tool_at"], "2026-04-17T00:59:30+00:00")
        self.assertEqual(data["sac_hooks_last_mcp_tool_name"], "mcp__orochi__channel_info")

    def test_detail_api_surfaces_hook_event_lists(self):
        self._post(
            self._base_payload(
                sac_hooks_recent_tools=[{"ts": "2026-04-17T00:00:00Z", "tool": "Grep"}],
                sac_hooks_recent_prompts=[{"ts": "2026-04-17T00:00:01Z", "prompt_preview": "?"}],
                sac_hooks_agent_calls=[{"ts": "2026-04-17T00:00:02Z", "input_preview": "x"}],
                background_tasks=[{"ts": "2026-04-17T00:00:03Z", "input_preview": "y"}],
                sac_hooks_tool_counts={"Grep": 1},
            )
        )
        resp = self._get_detail("hb-agent")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["sac_hooks_recent_tools"]), 1)
        self.assertEqual(data["sac_hooks_recent_tools"][0]["tool"], "Grep")
        self.assertEqual(len(data["sac_hooks_recent_prompts"]), 1)
        self.assertEqual(len(data["sac_hooks_agent_calls"]), 1)
        self.assertEqual(len(data["background_tasks"]), 1)
        self.assertEqual(data["sac_hooks_tool_counts"], {"Grep": 1})

    def test_missing_hook_fields_default_to_empty(self):
        """Registering without any hook fields leaves empty defaults —
        legacy agents that haven't wired hooks still register cleanly."""
        self._post(self._base_payload())
        resp = self._get_detail("hb-agent")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["sac_hooks_recent_tools"], [])
        self.assertEqual(data["sac_hooks_recent_prompts"], [])
        self.assertEqual(data["sac_hooks_agent_calls"], [])
        self.assertEqual(data["background_tasks"], [])
        self.assertEqual(data["sac_hooks_tool_counts"], {})
        self.assertEqual(data["sac_hooks_last_tool_at"], "")
        self.assertEqual(data["sac_hooks_last_tool_name"], "")
        self.assertEqual(data["sac_hooks_last_mcp_tool_at"], "")
        self.assertEqual(data["sac_hooks_last_mcp_tool_name"], "")

    def test_subsequent_heartbeat_replaces_hook_lists(self):
        """A fresh heartbeat must reflect the agent's current ring-buffer
        state — empty-list pushes wipe stale data (see registry.py
        comment on replace-on-present semantics)."""
        from hub.registry import get_agents

        self._post(
            self._base_payload(
                sac_hooks_recent_tools=[{"ts": "2026-04-17T00:00:00Z", "tool": "Edit"}],
                sac_hooks_tool_counts={"Edit": 1},
            )
        )
        self._post(
            self._base_payload(
                sac_hooks_recent_tools=[],
                sac_hooks_tool_counts={},
            )
        )
        agents = get_agents(workspace_id=self.ws.id)
        a = next(a for a in agents if a["name"] == "hb-agent")
        self.assertEqual(a["sac_hooks_recent_tools"], [])
        self.assertEqual(a["sac_hooks_tool_counts"], {})


class PaneActionSummaryRegistryTest(TestCase):
    """Smoke tests for the action-summary fields landed with the
    scitex-agent-container action subsystem.

    Covers the end-to-end pipe from ``heartbeat-push`` payload keys
    through registry merge and into ``/api/agents/<name>/detail/``:

      last_action_at / last_action / last_action_outcome /
      last_action_elapsed_s / action_counts /
      sac_hooks_p95_elapsed_s_by_action
    """

    def setUp(self):
        self.client = Client()
        self.ws = Workspace.objects.create(name="action-summary-ws")
        self.token = WorkspaceToken.objects.create(
            workspace=self.ws, label="action-test"
        )
        from hub.registry import _agents as _reg_agents

        _reg_agents.clear()

    def _post(self, payload):
        return self.client.post(
            "/api/agents/register/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def _get_detail(self, name):
        return self.client.get(
            f"/api/agents/{name}/detail/",
            data={"token": self.token.token},
        )

    def _base_payload(self, **overrides):
        payload = {
            "token": self.token.token,
            "name": "act-agent",
            "machine": "MBA",
            "role": "head",
        }
        payload.update(overrides)
        return payload

    def test_register_persists_action_summary_fields(self):
        from hub.registry import get_agents

        resp = self._post(
            self._base_payload(
                last_action_at="2026-04-17T02:00:00+00:00",
                last_action_name="nonce-probe",
                last_action_outcome="success",
                last_action_elapsed_s=3.2,
                action_counts={"nonce-probe:success": 42, "compact:success": 4},
                sac_hooks_p95_elapsed_s_by_action={"nonce-probe": 5.9, "compact": 9.0},
            )
        )
        self.assertEqual(resp.status_code, 200)
        agents = get_agents(workspace_id=self.ws.id)
        a = next(a for a in agents if a["name"] == "act-agent")
        self.assertEqual(a["last_action_at"], "2026-04-17T02:00:00+00:00")
        self.assertEqual(a["sac_hooks_last_action_name"], "nonce-probe")
        self.assertEqual(a["last_action_outcome"], "success")
        self.assertEqual(a["last_action_elapsed_s"], 3.2)
        self.assertEqual(a["action_counts"]["nonce-probe:success"], 42)
        self.assertEqual(a["sac_hooks_p95_elapsed_s_by_action"]["compact"], 9.0)

    def test_detail_api_surfaces_action_summary(self):
        self._post(
            self._base_payload(
                last_action_at="2026-04-17T02:05:00+00:00",
                last_action_name="compact",
                last_action_outcome="completion_timeout",
                last_action_elapsed_s=30.0,
            )
        )
        resp = self._get_detail("act-agent")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["last_action_at"], "2026-04-17T02:05:00+00:00")
        self.assertEqual(data["sac_hooks_last_action_name"], "compact")
        self.assertEqual(data["last_action_outcome"], "completion_timeout")
        self.assertEqual(data["last_action_elapsed_s"], 30.0)

    def test_missing_action_fields_default_to_empty(self):
        """Legacy agents that never ran an action still register and
        the detail endpoint returns well-defined empty defaults."""
        self._post(self._base_payload())
        resp = self._get_detail("act-agent")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["last_action_at"], "")
        self.assertEqual(data["sac_hooks_last_action_name"], "")
        self.assertEqual(data["last_action_outcome"], "")
        self.assertIsNone(data["last_action_elapsed_s"])
        self.assertEqual(data["action_counts"], {})
        self.assertEqual(data["sac_hooks_p95_elapsed_s_by_action"], {})
