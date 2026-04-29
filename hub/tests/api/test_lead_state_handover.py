"""Lead-state-handover (ZOO#12) — server-side API tests.

Covers the three new REST endpoints introduced by the
``feat/lead-state-handover-server`` PR:

  * ``POST /api/agents/<name>/snapshot``         (FR-A upsert)
  * ``GET  /api/agents/<name>/snapshot/latest``  (FR-A fetch)
  * ``GET  /api/agents/<name>/owner``            (FR-B priority/healthy)
  * ``GET  /api/agents/<name>/<uuid>/meta``      (FR-E session lookup)

Uses Django's bundled test client (no DRF) and :class:`TestCase` for
the DB transactional rollback — same pattern as
``hub/tests/api/test_a2a_sdk.py``.
"""

from __future__ import annotations

import json
import os
import uuid

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "orochi.settings")
django.setup()

from django.test import Client, TestCase  # noqa: E402

from hub.models import (  # noqa: E402
    AgentSession,
    AgentSnapshot,
    Workspace,
    WorkspaceToken,
)


def _make_workspace(name: str = "ws-zoo12") -> tuple[Workspace, str]:
    """Create a Workspace + WorkspaceToken; return (workspace, token_str)."""
    ws = Workspace.objects.create(name=name)
    tok = WorkspaceToken.objects.create(workspace=ws, label="test")
    return ws, tok.token


class SnapshotEndpointTests(TestCase):
    """FR-A — snapshot upsert + fetch round-trip."""

    def setUp(self) -> None:
        self.client = Client()
        self.ws, self.token = _make_workspace()

    def _url(self, agent: str, suffix: str = "") -> str:
        return f"/api/agents/{agent}/snapshot{suffix}/"

    def test_post_creates_snapshot(self) -> None:
        body = {
            "token": self.token,
            "payload": {"memory": {"a.md": "remember me"}, "transcript": []},
            "owner_host": "spartan",
        }
        resp = self.client.post(
            self._url("lead"),
            data=json.dumps(body),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["agent_name"], "lead")
        self.assertEqual(data["owner_host"], "spartan")
        self.assertTrue(data["bytes"] > 0)

        row = AgentSnapshot.objects.get(workspace=self.ws, agent_name="lead")
        self.assertEqual(row.payload["memory"]["a.md"], "remember me")
        self.assertEqual(row.owner_host, "spartan")

    def test_post_upserts_overwriting_payload(self) -> None:
        for owner, content in [("mba", "v1"), ("spartan", "v2")]:
            self.client.post(
                self._url("lead"),
                data=json.dumps(
                    {
                        "token": self.token,
                        "payload": {"memory": content},
                        "owner_host": owner,
                    }
                ),
                content_type="application/json",
            )
        # Single row remains, with the v2 payload.
        rows = AgentSnapshot.objects.filter(
            workspace=self.ws, agent_name="lead"
        )
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().payload["memory"], "v2")
        self.assertEqual(rows.first().owner_host, "spartan")

    def test_get_latest_returns_payload(self) -> None:
        AgentSnapshot.objects.create(
            workspace=self.ws,
            agent_name="lead",
            payload={"memory": "alpha"},
            owner_host="ywata-note-win",
        )
        resp = self.client.get(self._url("lead", "/latest") + f"?token={self.token}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["agent_name"], "lead")
        self.assertEqual(data["owner_host"], "ywata-note-win")
        self.assertEqual(data["payload"]["memory"], "alpha")

    def test_get_missing_returns_404(self) -> None:
        resp = self.client.get(self._url("ghost", "/latest") + f"?token={self.token}")
        self.assertEqual(resp.status_code, 404)

    def test_post_without_token_is_401(self) -> None:
        resp = self.client.post(
            self._url("lead"),
            data=json.dumps({"payload": {}}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_post_with_bad_token_is_401(self) -> None:
        resp = self.client.post(
            self._url("lead"),
            data=json.dumps({"token": "wks_bogus", "payload": {}}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_post_rejects_oversized_payload(self) -> None:
        # 3 MiB string blows past the 2 MiB cap.
        oversize = "x" * (3 * 1024 * 1024)
        resp = self.client.post(
            self._url("lead"),
            data=json.dumps(
                {
                    "token": self.token,
                    "payload": {"blob": oversize},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 413)

    def test_post_rejects_non_object_payload(self) -> None:
        resp = self.client.post(
            self._url("lead"),
            data=json.dumps({"token": self.token, "payload": "not-a-dict"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)


class OwnerEndpointTests(TestCase):
    """FR-B — owner endpoint exposes priority_list + healthy map."""

    def setUp(self) -> None:
        self.client = Client()
        self.ws, self.token = _make_workspace()
        # The registry's ``_agents`` dict is module-level state; reset
        # it so leak-through from a prior test class doesn't poison the
        # "unknown agent" assertions below.
        from hub.registry import _agents, _lock

        with _lock:
            _agents.clear()

    def test_owner_returns_empty_for_unknown_agent(self) -> None:
        resp = self.client.get(f"/api/agents/lead/owner/?token={self.token}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["agent"], "lead")
        self.assertEqual(data["current_host"], "")
        self.assertEqual(data["priority_list"], [])
        self.assertEqual(data["healthy"], {})

    def test_owner_reads_priority_list_from_registry(self) -> None:
        from hub.registry import register_agent

        register_agent(
            name="lead",
            workspace_id=self.ws.id,
            info={
                "machine": "spartan",
                "priority_list": ["spartan", "ywata-note-win", "mba"],
                "liveness": "online",
            },
        )
        resp = self.client.get(f"/api/agents/lead/owner/?token={self.token}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["current_host"], "spartan")
        self.assertEqual(
            data["priority_list"], ["spartan", "ywata-note-win", "mba"]
        )
        # Only spartan is online; the rest stay False until they
        # register their own heartbeat.
        self.assertTrue(data["healthy"]["spartan"])
        self.assertFalse(data["healthy"]["ywata-note-win"])
        self.assertFalse(data["healthy"]["mba"])

    def test_owner_unauthenticated_is_401(self) -> None:
        resp = self.client.get("/api/agents/lead/owner/")
        self.assertEqual(resp.status_code, 401)


class SessionMetaEndpointTests(TestCase):
    """FR-E — name+uuid → host/PID/ws lookup."""

    def setUp(self) -> None:
        self.client = Client()
        self.ws, self.token = _make_workspace()
        self.uuid = str(uuid.uuid4())
        AgentSession.objects.create(
            workspace=self.ws,
            agent_name="lead",
            instance_uuid=self.uuid,
            hostname="spartan",
            pid=4242,
            ws_session_id="specific-channels!abc",
            cardinality_enforced=True,
        )

    def test_meta_returns_session(self) -> None:
        url = f"/api/agents/lead/{self.uuid}/meta/?token={self.token}"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["instance_uuid"], self.uuid)
        self.assertEqual(data["hostname"], "spartan")
        self.assertEqual(data["pid"], 4242)
        self.assertTrue(data["cardinality_enforced"])
        self.assertIsNone(data["disconnected_at"])

    def test_meta_unknown_returns_404(self) -> None:
        bogus = str(uuid.uuid4())
        resp = self.client.get(
            f"/api/agents/lead/{bogus}/meta/?token={self.token}"
        )
        self.assertEqual(resp.status_code, 404)
