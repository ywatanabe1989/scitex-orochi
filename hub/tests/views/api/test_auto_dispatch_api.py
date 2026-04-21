"""Tests for ``/api/auto-dispatch/{fire,status}/`` (Phase 1c msg#16477)."""

from __future__ import annotations

import json
import time
from unittest import mock

from django.test import Client, TestCase, override_settings

from hub import auto_dispatch as ad
from hub.models import Workspace, WorkspaceToken
from hub.registry import _agents, _connections, _lock

_INMEM_CHANNELS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}


@override_settings(CHANNEL_LAYERS=_INMEM_CHANNELS)
class AutoDispatchStatusTest(TestCase):
    """``GET /api/auto-dispatch/status/``."""

    def setUp(self):
        self.client = Client()
        self.ws = Workspace.objects.create(name="ad-status-ws")
        self.tok = WorkspaceToken.objects.create(
            workspace=self.ws, token="wks_statustok"
        )
        with _lock:
            _agents.clear()
            _connections.clear()

    def tearDown(self):
        with _lock:
            _agents.clear()
            _connections.clear()

    # ---- Auth ----------------------------------------------------------

    def test_missing_token_returns_401(self):
        resp = self.client.get("/api/auto-dispatch/status/")
        self.assertEqual(resp.status_code, 401)
        body = json.loads(resp.content)
        self.assertIn("token", body["error"])

    def test_invalid_token_returns_401(self):
        resp = self.client.get("/api/auto-dispatch/status/?token=nope")
        self.assertEqual(resp.status_code, 401)

    # ---- Body ----------------------------------------------------------

    def test_empty_registry_returns_empty_array(self):
        resp = self.client.get(
            f"/api/auto-dispatch/status/?token={self.tok.token}"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(resp.content), [])

    def test_surfaces_idle_streak_and_cooldown(self):
        now = time.time()
        with _lock:
            _agents["head-mba"] = {
                "name": "head-mba",
                "workspace_id": self.ws.id,
                "subagent_count": 0,
                "idle_streak": 1,
                "auto_dispatch_last_fire_ts": now - 100,  # 100s ago
            }
            _agents["head-nas"] = {
                "name": "head-nas",
                "workspace_id": self.ws.id,
                "subagent_count": 2,
                "idle_streak": 0,
                "auto_dispatch_last_fire_ts": None,
            }

        resp = self.client.get(
            f"/api/auto-dispatch/status/?token={self.tok.token}"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        rows = json.loads(resp.content)
        names = {r["agent"] for r in rows}
        self.assertEqual(names, {"head-mba", "head-nas"})
        mba = next(r for r in rows if r["agent"] == "head-mba")
        self.assertEqual(mba["idle_streak"], 1)
        self.assertTrue(mba["cooldown_active"])
        self.assertGreater(mba["cooldown_remaining_s"], 0)
        self.assertEqual(mba["lane"], "infrastructure")
        nas = next(r for r in rows if r["agent"] == "head-nas")
        self.assertFalse(nas["cooldown_active"])
        self.assertIsNone(nas["last_fire_at"])

    def test_non_head_agents_excluded(self):
        with _lock:
            _agents["worker-foo"] = {
                "name": "worker-foo",
                "workspace_id": self.ws.id,
                "subagent_count": 0,
            }
            _agents["healer-mba"] = {
                "name": "healer-mba",
                "workspace_id": self.ws.id,
                "subagent_count": 0,
            }
        resp = self.client.get(
            f"/api/auto-dispatch/status/?token={self.tok.token}"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(resp.content), [])

    def test_other_workspace_agents_filtered_out(self):
        other_ws = Workspace.objects.create(name="other")
        with _lock:
            _agents["head-spartan"] = {
                "name": "head-spartan",
                "workspace_id": other_ws.id,  # different workspace
                "subagent_count": 0,
            }
        resp = self.client.get(
            f"/api/auto-dispatch/status/?token={self.tok.token}"
        )
        self.assertEqual(resp.status_code, 200)
        # head-spartan lives in other_ws, should not leak.
        self.assertEqual(json.loads(resp.content), [])


@override_settings(CHANNEL_LAYERS=_INMEM_CHANNELS)
class AutoDispatchFireTest(TestCase):
    """``POST /api/auto-dispatch/fire/``."""

    def setUp(self):
        self.client = Client()
        self.ws = Workspace.objects.create(name="ad-fire-ws")
        self.tok = WorkspaceToken.objects.create(
            workspace=self.ws, token="wks_firetok"
        )
        with _lock:
            _agents.clear()
            _connections.clear()

    def tearDown(self):
        with _lock:
            _agents.clear()
            _connections.clear()

    def _post(self, body: dict) -> tuple[int, dict]:
        resp = self.client.post(
            "/api/auto-dispatch/fire/",
            data=json.dumps(body),
            content_type="application/json",
        )
        try:
            payload = json.loads(resp.content)
        except (json.JSONDecodeError, ValueError):
            payload = {}
        return resp.status_code, payload

    # ---- Auth / validation --------------------------------------------

    def test_missing_token_returns_401(self):
        code, body = self._post({"head": "mba"})
        self.assertEqual(code, 401)

    def test_missing_head_returns_400(self):
        code, body = self._post({"token": self.tok.token})
        self.assertEqual(code, 400)
        self.assertIn("head", body["error"])

    def test_agent_not_registered_returns_404(self):
        code, body = self._post({"token": self.tok.token, "head": "ghost"})
        self.assertEqual(code, 404)

    # ---- Happy path ----------------------------------------------------

    def test_fire_arms_cooldown_on_success(self):
        with _lock:
            _agents["head-mba"] = {
                "name": "head-mba",
                "workspace_id": self.ws.id,
                "subagent_count": 0,
                "idle_streak": 3,
                "auto_dispatch_last_fire_ts": None,
            }
        with mock.patch.object(
            ad, "_post_dispatch_message", return_value=999
        ), mock.patch.object(
            ad, "_run_pick_todo", return_value=None
        ):
            code, body = self._post(
                {
                    "token": self.tok.token,
                    "head": "mba",
                    "reason": "operator-manual",
                }
            )
        self.assertEqual(code, 200, body)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["decision"], "fired")
        self.assertEqual(body["message_id"], 999)
        with _lock:
            self.assertEqual(_agents["head-mba"]["idle_streak"], 0)
            self.assertIsNotNone(
                _agents["head-mba"]["auto_dispatch_last_fire_ts"]
            )

    def test_explicit_todo_overrides_pick_helper(self):
        with _lock:
            _agents["head-mba"] = {
                "name": "head-mba",
                "workspace_id": self.ws.id,
                "subagent_count": 0,
            }
        captured: dict = {}

        def _fake_post(agent_name, workspace_id, text, metadata):
            captured.update(metadata)
            return 1234

        with mock.patch.object(
            ad, "_post_dispatch_message", side_effect=_fake_post
        ), mock.patch.object(
            ad,
            "_run_pick_todo",
            side_effect=AssertionError("should not be called"),
        ):
            code, body = self._post(
                {
                    "token": self.tok.token,
                    "head": "mba",
                    "todo": 555,
                    "todo_title": "custom title",
                }
            )
        self.assertEqual(code, 200, body)
        self.assertEqual(body["pick"]["number"], 555)
        self.assertEqual(body["pick"]["title"], "custom title")
        self.assertEqual(captured["todo_number"], 555)
        self.assertEqual(captured["trigger"], "manual")

    def test_invalid_todo_type_returns_400(self):
        with _lock:
            _agents["head-mba"] = {
                "name": "head-mba",
                "workspace_id": self.ws.id,
            }
        code, body = self._post(
            {"token": self.tok.token, "head": "mba", "todo": "not-an-int"}
        )
        self.assertEqual(code, 400)
