"""Tests for GET /api/connectivity/ — live connectivity map.

Covers:
1. Response shape: has nodes, edges, machine_liveness, source, ts.
2. source=="live" (not the old hardcoded "static").
3. Machine nodes get liveness from the agent registry.
4. Bastion status tracks its host machine's liveness.
5. Edge status tracks destination machine's liveness.
6. _machine_liveness: worst-of-N per machine, defaults to offline.
"""

import time

from django.contrib.auth.models import User
from django.test import Client, TestCase

from hub.models import Workspace, WorkspaceMember
from hub.registry import _agents as _reg
from hub.registry import register_agent
from hub.views.api._misc import _machine_liveness


class MachineLivenessTest(TestCase):
    """Unit tests for _machine_liveness() helper."""

    def setUp(self):
        self.ws = Workspace.objects.create(name="lv-ws")
        _reg.clear()

    def _reg_agent(self, name, machine, idle_secs=30):
        register_agent(name, workspace_id=self.ws.id, info={"machine": machine})
        _reg[name]["last_action"] = time.time() - idle_secs

    def test_empty_registry_returns_empty(self):
        self.assertEqual(_machine_liveness(workspace_id=self.ws.id), {})

    def test_online_agent_maps_to_machine(self):
        self._reg_agent("head@mba", "mba", idle_secs=30)
        lv = _machine_liveness(workspace_id=self.ws.id)
        self.assertIn("mba", lv)
        self.assertEqual(lv["mba"], "online")

    def test_stale_agent_maps_machine_stale(self):
        self._reg_agent("head@mba", "mba", idle_secs=700)
        lv = _machine_liveness(workspace_id=self.ws.id)
        self.assertEqual(lv["mba"], "stale")

    def test_worst_case_wins(self):
        """Two agents on mba: one online, one stale → machine is stale."""
        self._reg_agent("head@mba", "mba", idle_secs=30)
        self._reg_agent("worker@mba", "mba", idle_secs=700)
        lv = _machine_liveness(workspace_id=self.ws.id)
        self.assertEqual(lv["mba"], "stale")

    def test_fqdn_stripped_to_shortname(self):
        """machine='mba.local' → key should be 'mba'."""
        self._reg_agent("head@mba", "mba.local", idle_secs=30)
        lv = _machine_liveness(workspace_id=self.ws.id)
        self.assertIn("mba", lv)
        self.assertNotIn("mba.local", lv)

    def test_missing_machine_field_ignored(self):
        register_agent("anon", workspace_id=self.ws.id, info={})
        lv = _machine_liveness(workspace_id=self.ws.id)
        self.assertNotIn("", lv)


class ConnectivityApiTest(TestCase):
    """Integration tests for GET /api/connectivity/."""

    def setUp(self):
        self.ws = Workspace.objects.create(name="conn-ws")
        self.host = f"{self.ws.name}.lvh.me"
        self.user = User.objects.create_user(username="u", password="x")
        WorkspaceMember.objects.create(workspace=self.ws, user=self.user, role="member")
        self.client = Client()
        self.client.force_login(self.user)
        _reg.clear()

    def _get(self):
        return self.client.get("/api/connectivity/", HTTP_HOST=self.host)

    def _reg_agent(self, name, machine, idle_secs=30):
        register_agent(name, workspace_id=self.ws.id, info={"machine": machine})
        _reg[name]["last_action"] = time.time() - idle_secs

    # ── shape ─────────────────────────────────────────────────────────

    def test_response_has_required_keys(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for key in ("nodes", "edges", "machine_liveness", "source", "ts"):
            self.assertIn(key, data, f"missing key: {key}")

    def test_source_is_live(self):
        resp = self._get()
        self.assertEqual(resp.json()["source"], "live")

    def test_nodes_have_required_fields(self):
        resp = self._get()
        for node in resp.json()["nodes"]:
            self.assertIn("id", node)
            self.assertIn("type", node)
            self.assertIn("status", node)

    def test_edges_have_required_fields(self):
        resp = self._get()
        for edge in resp.json()["edges"]:
            self.assertIn("source", edge)
            self.assertIn("target", edge)
            self.assertIn("status", edge)
            self.assertIn("method", edge)

    # ── live status ───────────────────────────────────────────────────

    def test_offline_machine_node_shows_off_status(self):
        """No agents on mba → mba node status = 'off'."""
        resp = self._get()
        mba_node = next(
            (n for n in resp.json()["nodes"] if n["id"] == "mba"), None
        )
        self.assertIsNotNone(mba_node)
        self.assertEqual(mba_node["status"], "off")

    def test_online_machine_node_shows_ok(self):
        self._reg_agent("head@mba", "mba", idle_secs=30)
        resp = self._get()
        mba_node = next(n for n in resp.json()["nodes"] if n["id"] == "mba")
        self.assertEqual(mba_node["status"], "ok")
        self.assertEqual(mba_node["liveness"], "online")

    def test_stale_machine_node_shows_stale(self):
        self._reg_agent("head@mba", "mba", idle_secs=700)
        resp = self._get()
        mba_node = next(n for n in resp.json()["nodes"] if n["id"] == "mba")
        self.assertEqual(mba_node["status"], "stale")

    def test_bastion_status_tracks_host_machine(self):
        """bastion-mba status == mba status."""
        self._reg_agent("head@mba", "mba", idle_secs=30)
        resp = self._get()
        data = resp.json()
        mba_node = next(n for n in data["nodes"] if n["id"] == "mba")
        bastion_mba = next(n for n in data["nodes"] if n["id"] == "bastion-mba")
        self.assertEqual(mba_node["status"], bastion_mba["status"])

    def test_edge_status_tracks_destination(self):
        """Edge mba→nas: status == nas machine liveness."""
        # nas has no agent → should be "off"
        self._reg_agent("head@mba", "mba", idle_secs=30)
        resp = self._get()
        edge = next(
            e for e in resp.json()["edges"]
            if e["source"] == "mba" and e["target"] == "nas"
        )
        self.assertEqual(edge["status"], "off")

    def test_machine_liveness_in_response(self):
        self._reg_agent("head@mba", "mba", idle_secs=30)
        resp = self._get()
        ml = resp.json()["machine_liveness"]
        self.assertIn("mba", ml)
        self.assertEqual(ml["mba"], "online")
