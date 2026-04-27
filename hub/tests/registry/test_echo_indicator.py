"""Tests for the 4th liveness indicator — echo round-trip (#259).

Covers the registry-side contract for the new echo fields:

  - ``update_echo_pong(name, rtt_ms)`` populates the three fields
    (``last_echo_rtt_ms`` / ``last_echo_ok_ts`` / ``last_nonce_echo_at``)
    atomically.
  - The prev-preserve list in ``register_agent`` keeps those fields
    across re-registers / heartbeats that omit them, so the 4th LED
    doesn't flicker grey-pending each cycle (per the prev-preserve
    pitfall memory).
  - ``GET /api/agents/<name>/detail/`` surfaces the new fields in the
    response so the dashboard's per-agent detail panel can display
    them without a second round-trip.
"""

import json
import time

from django.test import Client, TestCase

from hub.models import Workspace, WorkspaceToken


class UpdateEchoPongRegistryTests(TestCase):
    """Verify the registry setter writes all three fields atomically."""

    def setUp(self):
        from hub.registry import _agents, _connections

        _agents.clear()
        _connections.clear()
        self.ws = Workspace.objects.create(name="echo-test-ws")

    def _seed_agent(self, name="echo-agent"):
        from hub.registry import register_agent

        register_agent(
            name,
            self.ws.id,
            {
                "agent_id": name,
                "orochi_machine": "MBA",
                "role": "head",
            },
        )

    def test_update_echo_pong_sets_all_three_fields(self):
        from hub.registry import _agents, update_echo_pong

        self._seed_agent()
        before = time.time()
        update_echo_pong("echo-agent", 42.5)
        after = time.time()

        a = _agents["echo-agent"]
        self.assertEqual(a["last_echo_rtt_ms"], 42.5)
        self.assertIsNotNone(a["last_echo_ok_ts"])
        self.assertGreaterEqual(a["last_echo_ok_ts"], before)
        self.assertLessEqual(a["last_echo_ok_ts"], after)
        # The ISO timestamp consumed by renderAgentLeds must be set
        # — this is the field the LED renderer pins on.
        self.assertIsInstance(a["last_nonce_echo_at"], str)
        self.assertTrue(a["last_nonce_echo_at"].endswith("+00:00"))

    def test_update_echo_pong_unknown_agent_is_silent_noop(self):
        """An echo_pong for an unknown agent must not raise / corrupt state."""
        from hub.registry import _agents, update_echo_pong

        update_echo_pong("never-registered", 17.0)
        self.assertNotIn("never-registered", _agents)

    def test_register_agent_preserves_echo_fields_across_heartbeat(self):
        """A subsequent register/heartbeat that omits echo fields must NOT
        wipe them. This is the prev-preserve pitfall — without it, every
        heartbeat would flicker the 4th LED to grey-pending."""
        from hub.registry import _agents, register_agent, update_echo_pong

        self._seed_agent()
        update_echo_pong("echo-agent", 55.0)
        snapshot = {
            "last_echo_rtt_ms": _agents["echo-agent"]["last_echo_rtt_ms"],
            "last_echo_ok_ts": _agents["echo-agent"]["last_echo_ok_ts"],
            "last_nonce_echo_at": _agents["echo-agent"]["last_nonce_echo_at"],
        }

        # Simulate a re-register (e.g. WS reconnect) that doesn't carry
        # the echo fields — they must survive.
        register_agent(
            "echo-agent",
            self.ws.id,
            {
                "agent_id": "echo-agent",
                "orochi_machine": "MBA",
                "role": "head",
            },
        )

        a = _agents["echo-agent"]
        self.assertEqual(a["last_echo_rtt_ms"], snapshot["last_echo_rtt_ms"])
        self.assertEqual(a["last_echo_ok_ts"], snapshot["last_echo_ok_ts"])
        self.assertEqual(a["last_nonce_echo_at"], snapshot["last_nonce_echo_at"])

    def test_get_agents_payload_surfaces_echo_fields(self):
        """The dashboard read path (get_agents) must include the echo
        fields so the LED renderer can consume ``last_nonce_echo_at``."""
        from hub.registry import get_agents, update_echo_pong

        self._seed_agent()
        update_echo_pong("echo-agent", 33.0)
        payload = next(
            a for a in get_agents(workspace_id=self.ws.id) if a["name"] == "echo-agent"
        )
        self.assertIn("last_nonce_echo_at", payload)
        self.assertIn("last_echo_rtt_ms", payload)
        self.assertIn("last_echo_ok_ts", payload)
        self.assertEqual(payload["last_echo_rtt_ms"], 33.0)
        self.assertIsNotNone(payload["last_nonce_echo_at"])
        self.assertTrue(payload["last_echo_ok_ts"].endswith("+00:00"))

    def test_get_agents_payload_echo_fields_absent_when_never_set(self):
        """Agents that have never echoed back should report None for the
        echo fields — the LED renderer treats None as grey-pending."""
        from hub.registry import get_agents

        self._seed_agent()
        payload = next(
            a for a in get_agents(workspace_id=self.ws.id) if a["name"] == "echo-agent"
        )
        self.assertIsNone(payload["last_nonce_echo_at"])
        self.assertIsNone(payload["last_echo_rtt_ms"])
        self.assertIsNone(payload["last_echo_ok_ts"])


class AgentDetailEchoFieldsTests(TestCase):
    """End-to-end: register → update_echo_pong → GET /api/agents/<n>/detail/."""

    def setUp(self):
        from hub.registry import _agents, _connections

        _agents.clear()
        _connections.clear()
        self.client = Client()
        self.ws = Workspace.objects.create(name="echo-detail-ws")
        self.token = WorkspaceToken.objects.create(
            workspace=self.ws, label="echo-test"
        )

    def _post_register(self, name="echo-agent"):
        return self.client.post(
            "/api/agents/register/",
            data=json.dumps(
                {
                    "token": self.token.token,
                    "name": name,
                    "orochi_machine": "MBA",
                    "role": "head",
                }
            ),
            content_type="application/json",
        )

    def _get_detail(self, name):
        return self.client.get(
            f"/api/agents/{name}/detail/",
            data={"token": self.token.token},
        )

    def test_detail_api_surfaces_echo_fields_after_pong(self):
        from hub.registry import update_echo_pong

        self._post_register("echo-agent")
        update_echo_pong("echo-agent", 77.7)

        resp = self._get_detail("echo-agent")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("last_nonce_echo_at", data)
        self.assertIn("last_echo_rtt_ms", data)
        self.assertIn("last_echo_ok_ts", data)
        self.assertEqual(data["last_echo_rtt_ms"], 77.7)
        self.assertIsNotNone(data["last_nonce_echo_at"])

    def test_detail_api_echo_fields_default_when_never_pong(self):
        """An agent that registered but never echoed back must have the
        new fields present (not missing keys) and set to None — the
        dashboard relies on the keys existing for its grey-pending
        rendering."""
        self._post_register("echo-agent")
        resp = self._get_detail("echo-agent")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("last_nonce_echo_at", data)
        self.assertIn("last_echo_rtt_ms", data)
        self.assertIn("last_echo_ok_ts", data)
        self.assertIsNone(data["last_nonce_echo_at"])
        self.assertIsNone(data["last_echo_rtt_ms"])
        self.assertIsNone(data["last_echo_ok_ts"])
