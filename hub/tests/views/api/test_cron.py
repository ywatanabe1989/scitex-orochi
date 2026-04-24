"""Tests for ``GET /api/cron/`` — fleet-wide cron status aggregator.

Phase 2 of the Orochi unified cron (msg#16406 / msg#16408). The endpoint
projects the in-memory registry's per-agent ``cron_jobs`` arrays into a
host-keyed dict consumable by the Machines tab.

Invariants covered:

* Empty registry → ``{"hosts": {}}``.
* Two hosts with jobs → both surface.
* Auth required (session-only — matches ``/api/agents/registry/`` pattern).
* Stale heartbeat (>10 min) marks the host entry ``stale: true``.
* Agents missing ``cron_jobs`` → empty jobs array, not a 500.
* Freshness wins when two agents share a host.
* Heartbeat round-trip: a register POST carrying ``cron_jobs`` surfaces
  on the aggregator (end-to-end contract pin).
* Prev-preserve: a follow-up heartbeat without ``cron_jobs`` does not
  wipe the stored array.
"""

import json
import time

from django.contrib.auth.models import User
from django.test import Client, TestCase

from hub.models import Workspace, WorkspaceMember, WorkspaceToken


class ApiCronTest(TestCase):
    """Aggregator shape + auth + staleness + collision rules."""

    # ``WorkspaceSubdomainMiddleware`` parses ``<slug>.lvh.me`` into
    # ``request.workspace``. Mirrors the pattern used by
    # ``test_admin_subscribe.py``.
    SUBDOMAIN_HOST = "cron-ws.lvh.me"

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="cron-test-user", password="pw"
        )
        self.ws = Workspace.objects.create(name="cron-ws")
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.user, role="member"
        )
        self.token = WorkspaceToken.objects.create(workspace=self.ws, label="cron")
        self.client.force_login(self.user)
        # Clear the in-memory registry between tests so stale fixtures
        # from other suites don't leak in.
        from hub.registry import _agents

        _agents.clear()

    def _post_heartbeat(self, payload):
        """Register-endpoint is token-authed and workspace-agnostic; the
        token itself resolves the workspace, so we can hit it on the
        bare ``lvh.me`` host.
        """
        return self.client.post(
            "/api/agents/register/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_HOST="lvh.me",
        )

    def _get_cron(self, workspace_id=None):
        """GET the aggregator under the workspace subdomain so the
        subdomain middleware populates ``request.workspace``.
        """
        return self.client.get("/api/cron/", HTTP_HOST=self.SUBDOMAIN_HOST)

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def test_requires_authentication(self):
        """Session login is mandatory — anonymous GET is rejected (302/403)."""
        anon = Client()
        resp = anon.get("/api/cron/")
        self.assertIn(resp.status_code, (302, 401, 403))

    def test_empty_registry_returns_empty_hosts(self):
        """Fresh workspace with no agents → ``{"hosts": {}}`` (not 404)."""
        resp = self._get_cron()
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data, {"hosts": {}})

    # ------------------------------------------------------------------
    # Populated registry
    # ------------------------------------------------------------------

    def test_two_hosts_both_visible(self):
        """Two heartbeats with distinct ``machine`` → two host entries."""
        self._post_heartbeat(
            {
                "token": self.token.token,
                "name": "head-mba",
                "machine": "mba",
                "cron_jobs": [
                    {
                        "name": "machine-heartbeat",
                        "interval": 120,
                        "last_run": time.time() - 60,
                        "last_exit": 0,
                        "next_run": time.time() + 60,
                    }
                ],
            }
        )
        self._post_heartbeat(
            {
                "token": self.token.token,
                "name": "head-nas",
                "machine": "nas",
                "cron_jobs": [
                    {
                        "name": "host-liveness-probe",
                        "interval": 120,
                        "last_run": time.time() - 30,
                        "last_exit": 0,
                        "next_run": time.time() + 90,
                    }
                ],
            }
        )
        resp = self._get_cron()
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("mba", data["hosts"])
        self.assertIn("nas", data["hosts"])
        self.assertEqual(data["hosts"]["mba"]["agent"], "head-mba")
        self.assertEqual(data["hosts"]["nas"]["agent"], "head-nas")
        self.assertEqual(len(data["hosts"]["mba"]["jobs"]), 1)
        self.assertEqual(
            data["hosts"]["mba"]["jobs"][0]["name"], "machine-heartbeat"
        )
        self.assertFalse(data["hosts"]["mba"]["stale"])

    def test_missing_cron_jobs_field_returns_empty_array(self):
        """Legacy agent without ``cron_jobs`` in its heartbeat still
        renders as a host entry with ``jobs: []`` — the aggregator must
        never 500 on a missing field.
        """
        self._post_heartbeat(
            {
                "token": self.token.token,
                "name": "head-legacy",
                "machine": "legacy-host",
            }
        )
        resp = self._get_cron()
        self.assertEqual(resp.status_code, 200)
        hosts = resp.json()["hosts"]
        self.assertIn("legacy-host", hosts)
        self.assertEqual(hosts["legacy-host"]["jobs"], [])
        self.assertFalse(hosts["legacy-host"]["stale"])

    def test_stale_heartbeat_marks_host_stale(self):
        """Heartbeat >10 min old flips ``stale`` to True while keeping the
        last-known ``jobs`` array visible (so the UI can show a stale
        warning rather than dropping the card).
        """
        # Post a normal heartbeat then rewrite last_heartbeat to force staleness.
        self._post_heartbeat(
            {
                "token": self.token.token,
                "name": "head-stale",
                "machine": "stale-host",
                "cron_jobs": [
                    {
                        "name": "machine-heartbeat",
                        "interval": 120,
                        "last_run": time.time() - 30,
                        "last_exit": 0,
                        "next_run": time.time() + 90,
                    }
                ],
            }
        )
        from hub.registry import _agents

        _agents["head-stale"]["last_heartbeat"] = time.time() - 1200  # 20 min ago

        resp = self._get_cron()
        self.assertEqual(resp.status_code, 200)
        host = resp.json()["hosts"]["stale-host"]
        self.assertTrue(host["stale"])
        # Stale cards still carry their last-known jobs.
        self.assertEqual(len(host["jobs"]), 1)
        self.assertEqual(host["jobs"][0]["name"], "machine-heartbeat")

    def test_fresh_heartbeat_not_stale(self):
        """Heartbeat inside the 10-minute window must not be marked stale."""
        self._post_heartbeat(
            {
                "token": self.token.token,
                "name": "head-fresh",
                "machine": "fresh-host",
                "cron_jobs": [],
            }
        )
        resp = self._get_cron()
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["hosts"]["fresh-host"]["stale"])

    def test_preserves_cron_jobs_across_heartbeats(self):
        """A follow-up heartbeat WITHOUT ``cron_jobs`` must not wipe the
        previously stored array — transient state-file read failures on
        the local daemon shouldn't blank the Machines tab every 30s.
        """
        jobs = [
            {
                "name": "hungry-signal",
                "interval": 120,
                "last_run": time.time() - 10,
                "last_exit": 0,
                "next_run": time.time() + 110,
            }
        ]
        self._post_heartbeat(
            {
                "token": self.token.token,
                "name": "head-preserve",
                "machine": "preserve-host",
                "cron_jobs": jobs,
            }
        )
        # Second heartbeat omits cron_jobs entirely.
        self._post_heartbeat(
            {
                "token": self.token.token,
                "name": "head-preserve",
                "machine": "preserve-host",
            }
        )
        resp = self._get_cron()
        self.assertEqual(resp.status_code, 200)
        host = resp.json()["hosts"]["preserve-host"]
        self.assertEqual(len(host["jobs"]), 1)
        self.assertEqual(host["jobs"][0]["name"], "hungry-signal")

    def test_freshness_wins_when_two_agents_share_host(self):
        """If two agents report from the same machine, the freshest
        non-empty ``cron_jobs`` wins (heads are the authoritative source
        of daemon state — the non-head agent's empty array mustn't clobber
        the head's populated one).
        """
        # Head posts first, with jobs.
        self._post_heartbeat(
            {
                "token": self.token.token,
                "name": "head-mba",
                "machine": "mba",
                "cron_jobs": [
                    {
                        "name": "machine-heartbeat",
                        "interval": 120,
                        "last_run": time.time() - 30,
                        "last_exit": 0,
                        "next_run": time.time() + 90,
                    }
                ],
            }
        )
        # Healer posts after, with NO jobs (no daemon on this agent).
        self._post_heartbeat(
            {
                "token": self.token.token,
                "name": "healer-mba",
                "machine": "mba",
            }
        )
        resp = self._get_cron()
        self.assertEqual(resp.status_code, 200)
        host = resp.json()["hosts"]["mba"]
        # Head's jobs array wins even though healer's heartbeat is newer.
        self.assertEqual(len(host["jobs"]), 1)
        self.assertEqual(host["jobs"][0]["name"], "machine-heartbeat")

    def test_response_shape_matches_spec(self):
        """Per-host entry contains {agent, last_heartbeat_at, stale, jobs}
        and nothing unexpected. Pins the contract for downstream UI.
        """
        self._post_heartbeat(
            {
                "token": self.token.token,
                "name": "head-mba",
                "machine": "mba",
                "cron_jobs": [
                    {
                        "name": "machine-heartbeat",
                        "interval": 120,
                        "last_run": time.time() - 60,
                        "last_exit": 0,
                        "next_run": time.time() + 60,
                    }
                ],
            }
        )
        resp = self._get_cron()
        body = resp.json()
        self.assertEqual(set(body.keys()), {"hosts"})
        host = body["hosts"]["mba"]
        self.assertEqual(
            set(host.keys()), {"agent", "last_heartbeat_at", "stale", "jobs"}
        )
        self.assertIsInstance(host["jobs"], list)

    def test_last_exit_nonzero_surfaces(self):
        """Non-zero ``last_exit`` reaches the aggregator verbatim — the
        Machines tab reads it to flip the status icon to the warning
        glyph.
        """
        self._post_heartbeat(
            {
                "token": self.token.token,
                "name": "head-mba",
                "machine": "mba",
                "cron_jobs": [
                    {
                        "name": "chrome-watchdog",
                        "interval": 60,
                        "last_run": time.time() - 3600,
                        "last_exit": 1,
                        "next_run": time.time(),
                    }
                ],
            }
        )
        resp = self._get_cron()
        jobs = resp.json()["hosts"]["mba"]["jobs"]
        self.assertEqual(jobs[0]["last_exit"], 1)
        self.assertEqual(jobs[0]["name"], "chrome-watchdog")

    def test_host_key_falls_back_to_hostname_when_machine_absent(self):
        """If a heartbeat omits ``machine`` we still produce a row
        (``hostname`` fallback) instead of silently dropping it.
        """
        self._post_heartbeat(
            {
                "token": self.token.token,
                "name": "bare-agent",
                "hostname": "bare-host.example",
                "cron_jobs": [],
            }
        )
        resp = self._get_cron()
        hosts = resp.json()["hosts"]
        self.assertIn("bare-host.example", hosts)

    # ------------------------------------------------------------------
    # ``?host=<name>`` filter + token-auth path (lead msg#16684 /
    # PR #346 follow-up — the MCP ``cron_status`` tool relies on both).
    # ------------------------------------------------------------------

    def test_host_filter_returns_only_matching_host(self):
        """``GET /api/cron/?host=mba`` returns just the mba row, not nas."""
        self._post_heartbeat(
            {
                "token": self.token.token,
                "name": "head-mba",
                "machine": "mba",
                "cron_jobs": [
                    {
                        "name": "machine-heartbeat",
                        "interval": 120,
                        "last_run": time.time() - 60,
                        "last_exit": 0,
                        "next_run": time.time() + 60,
                    }
                ],
            }
        )
        self._post_heartbeat(
            {
                "token": self.token.token,
                "name": "head-nas",
                "machine": "nas",
                "cron_jobs": [],
            }
        )
        resp = self.client.get(
            "/api/cron/?host=mba", HTTP_HOST=self.SUBDOMAIN_HOST
        )
        self.assertEqual(resp.status_code, 200)
        hosts = resp.json()["hosts"]
        self.assertEqual(set(hosts.keys()), {"mba"})
        self.assertEqual(hosts["mba"]["agent"], "head-mba")

    def test_host_filter_unknown_host_returns_empty_hosts(self):
        """Unknown host key → ``{"hosts": {}}`` (not 404)."""
        self._post_heartbeat(
            {
                "token": self.token.token,
                "name": "head-mba",
                "machine": "mba",
                "cron_jobs": [],
            }
        )
        resp = self.client.get(
            "/api/cron/?host=no-such-host", HTTP_HOST=self.SUBDOMAIN_HOST
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"hosts": {}})

    def test_token_auth_allows_mcp_sidecar_access(self):
        """MCP sidecars hit ``/api/cron/?token=wks_...&agent=<self>``
        on the bare domain. Session-less requests with a valid workspace
        token must be accepted; this is the path the MCP ``cron_status``
        tool uses.
        """
        self._post_heartbeat(
            {
                "token": self.token.token,
                "name": "head-mba",
                "machine": "mba",
                "cron_jobs": [],
            }
        )
        anon = Client()
        resp = anon.get(
            f"/api/cron/?token={self.token.token}&agent=cron-status-probe",
            HTTP_HOST="lvh.me",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("mba", resp.json()["hosts"])

    def test_token_auth_with_host_filter(self):
        """Token auth + ``?host=<name>`` compose — MCP callers pass both."""
        self._post_heartbeat(
            {
                "token": self.token.token,
                "name": "head-mba",
                "machine": "mba",
                "cron_jobs": [],
            }
        )
        self._post_heartbeat(
            {
                "token": self.token.token,
                "name": "head-nas",
                "machine": "nas",
                "cron_jobs": [],
            }
        )
        anon = Client()
        resp = anon.get(
            f"/api/cron/?token={self.token.token}&agent=probe&host=nas",
            HTTP_HOST="lvh.me",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(set(resp.json()["hosts"].keys()), {"nas"})

    def test_token_auth_rejects_invalid_token(self):
        """A bad token → 401 (not a silent empty response)."""
        anon = Client()
        resp = anon.get(
            "/api/cron/?token=wks_bogus&agent=probe",
            HTTP_HOST="lvh.me",
        )
        self.assertEqual(resp.status_code, 401)
