"""Tests for pane_state → liveness classification in GET /api/agents/.

Ensures the liveness classifier in hub/registry/_payload.py maps
each recognised pane_state value to the correct liveness label.
"""

import time

from django.test import Client, TestCase

from hub.models import Workspace, WorkspaceMember, WorkspaceToken
from hub.registry import _agents as _reg
from hub.registry import register_agent


class LivenessPaneStateTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.ws = Workspace.objects.create(name="lps-test-ws")
        self.token = WorkspaceToken.objects.create(workspace=self.ws, label="ci")
        from django.contrib.auth.models import User

        self.user = User.objects.create_user(username="lps-tester", password="x")
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.user, role="member"
        )
        _reg.clear()

    def _register(self, name, **extra):
        register_agent(name, workspace_id=self.ws.id, info={"machine": "lps-host", **extra})

    def _inject(self, name, **fields):
        if name in _reg:
            _reg[name].update(fields)

    def _get(self):
        self.client.force_login(self.user)
        return self.client.get(
            "/api/agents/", HTTP_HOST=f"{self.ws.name}.lvh.me"
        )

    def _liveness_for(self, name):
        data = self._get().json()
        for a in data:
            if a["name"] == name:
                return a["liveness"]
        return None

    def test_running_pane_state_is_online(self):
        self._register("a-running")
        self._inject("a-running", orochi_pane_state="running", last_action=time.time())
        self.assertEqual(self._liveness_for("a-running"), "online")

    def test_stale_pane_state_is_stale(self):
        self._register("a-stale")
        self._inject("a-stale", orochi_pane_state="stale", last_action=time.time())
        self.assertEqual(self._liveness_for("a-stale"), "stale")

    def test_y_n_prompt_pane_state_is_idle(self):
        self._register("a-ynprompt")
        self._inject("a-ynprompt", orochi_pane_state="y_n_prompt", last_action=time.time())
        self.assertEqual(self._liveness_for("a-ynprompt"), "idle")

    def test_compose_pending_pane_state_is_idle(self):
        self._register("a-compose")
        self._inject("a-compose", orochi_pane_state="compose_pending_unsent", last_action=time.time())
        self.assertEqual(self._liveness_for("a-compose"), "idle")

    def test_bypass_permissions_pane_state_is_idle(self):
        self._register("a-bypass")
        self._inject("a-bypass", orochi_pane_state="bypass_permissions_prompt", last_action=time.time())
        self.assertEqual(self._liveness_for("a-bypass"), "idle")

    def test_limit_reached_pane_state_is_idle(self):
        """limit_reached = Anthropic rate-limit visible; agent is alive but
        temporarily blocked — must be classified as idle, not stale."""
        self._register("a-limited")
        self._inject(
            "a-limited",
            orochi_pane_state="limit_reached",
            last_action=time.time() - 700,
        )
        self.assertEqual(self._liveness_for("a-limited"), "idle")

    def test_unknown_pane_state_falls_through_to_time_based(self):
        """Unrecognised pane state falls back to idle_seconds heuristic."""
        self._register("a-unknown")
        self._inject(
            "a-unknown",
            orochi_pane_state="some_future_state",
            last_action=time.time() - 700,
        )
        self.assertEqual(self._liveness_for("a-unknown"), "stale")
