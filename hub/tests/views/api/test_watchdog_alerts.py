"""Tests for GET /api/watchdog/alerts/.

Covers:
1. Empty alerts when all agents are online with no task.
2. idle/stale agent with active task → alert (kind=agent_stale).
3. Subagent count non-zero for >10 min → alert (kind=subagent_stuck).
4. Stale agent already emitted should NOT also emit subagent_stuck.
5. Thresholds block in response includes subagent_stuck_seconds.

Note: ``liveness`` is computed dynamically in ``get_agents()`` from
``last_action`` / ``orochi_pane_state``; injecting it directly into
``_reg`` has no effect. Tests drive liveness via ``last_action`` timestamps.
"""

import time

from django.contrib.auth.models import User
from django.test import Client, TestCase

from hub.models import Workspace, WorkspaceMember
from hub.registry import _agents as _reg
from hub.registry import register_agent


class WatchdogAlertsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.ws = Workspace.objects.create(name="wd-test-ws")
        self.host = f"{self.ws.name}.lvh.me"
        self.user = User.objects.create_user(username="tester", password="x")
        WorkspaceMember.objects.create(workspace=self.ws, user=self.user, role="member")
        _reg.clear()
        self.client.force_login(self.user)

    def _get(self):
        return self.client.get("/api/watchdog/alerts/", HTTP_HOST=self.host)

    def _register(self, name, **extra):
        info = {"machine": "test-host", "role": "test", **extra}
        register_agent(name, workspace_id=self.ws.id, info=info)

    def _inject(self, name, **fields):
        """Directly patch the in-memory registry entry."""
        if name in _reg:
            _reg[name].update(fields)

    def _make_stale(self, name, task=""):
        """Set last_action to >600s ago so liveness computes as stale."""
        self._inject(name, last_action=time.time() - 700, orochi_current_task=task)

    def _make_idle(self, name, task=""):
        """Set last_action to 200s ago so liveness computes as idle."""
        self._inject(name, last_action=time.time() - 200, orochi_current_task=task)

    def _make_online(self, name, task=""):
        """Set last_action to <120s ago so liveness computes as online."""
        self._inject(name, last_action=time.time() - 30, orochi_current_task=task)

    # ── tests ─────────────────────────────────────────────────────────

    def test_no_alerts_when_all_online(self):
        self._register("agent-ok")
        self._make_online("agent-ok")
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["alerts"], [])

    def test_stale_agent_with_task_raises_alert(self):
        self._register("agent-stale")
        self._make_stale("agent-stale", task="implement #999")
        resp = self._get()
        data = resp.json()
        self.assertEqual(data["count"], 1)
        alert = data["alerts"][0]
        self.assertEqual(alert["agent"], "agent-stale")
        self.assertEqual(alert["kind"], "agent_stale")
        self.assertEqual(alert["severity"], "stale")
        self.assertEqual(alert["suggested_action"], "escalate")

    def test_idle_agent_with_task_raises_nudge_alert(self):
        self._register("agent-idle")
        self._make_idle("agent-idle", task="review PR #42")
        resp = self._get()
        data = resp.json()
        self.assertEqual(data["count"], 1)
        alert = data["alerts"][0]
        self.assertEqual(alert["kind"], "agent_stale")
        self.assertEqual(alert["severity"], "idle")
        self.assertEqual(alert["suggested_action"], "nudge")

    def test_online_agent_with_task_no_alert(self):
        self._register("agent-running")
        self._make_online("agent-running", task="running normally")
        resp = self._get()
        self.assertEqual(resp.json()["count"], 0)

    def test_subagent_stuck_alert_after_threshold(self):
        """Agent with subagent count >0 for >10 min raises subagent_stuck."""
        self._register("agent-subwedge")
        self._make_online("agent-subwedge")
        self._inject(
            "agent-subwedge",
            orochi_subagent_count=3,
            subagent_active_since=time.time() - 650,
        )
        resp = self._get()
        data = resp.json()
        self.assertEqual(data["count"], 1)
        alert = data["alerts"][0]
        self.assertEqual(alert["kind"], "subagent_stuck")
        self.assertEqual(alert["severity"], "stale")
        self.assertEqual(alert["subagent_count"], 3)
        self.assertGreaterEqual(alert["subagent_stuck_seconds"], 600)

    def test_subagent_below_threshold_no_alert(self):
        self._register("agent-subrun")
        self._make_online("agent-subrun")
        self._inject(
            "agent-subrun",
            orochi_subagent_count=2,
            subagent_active_since=time.time() - 300,
        )
        resp = self._get()
        self.assertEqual(resp.json()["count"], 0)

    def test_subagent_zero_count_no_alert(self):
        self._register("agent-nosub")
        self._make_online("agent-nosub")
        self._inject(
            "agent-nosub",
            orochi_subagent_count=0,
            subagent_active_since=time.time() - 1000,
        )
        resp = self._get()
        self.assertEqual(resp.json()["count"], 0)

    def test_stale_agent_not_duplicated_as_subagent_stuck(self):
        """Agent already emitted as agent_stale should not also be subagent_stuck."""
        self._register("agent-dual")
        self._make_stale("agent-dual", task="stuck task")
        self._inject(
            "agent-dual",
            orochi_subagent_count=5,
            subagent_active_since=time.time() - 700,
        )
        resp = self._get()
        data = resp.json()
        # Only ONE alert despite matching both conditions
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["alerts"][0]["kind"], "agent_stale")

    def test_thresholds_in_response(self):
        resp = self._get()
        thresholds = resp.json()["thresholds"]
        self.assertIn("idle_seconds", thresholds)
        self.assertIn("stale_seconds", thresholds)
        self.assertIn("subagent_stuck_seconds", thresholds)
        self.assertEqual(thresholds["subagent_stuck_seconds"], 600)
