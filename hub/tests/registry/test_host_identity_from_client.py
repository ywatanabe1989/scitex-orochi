"""Regression tests for lead msg#15578 — host identity misreport.

Background
----------
Agent ``proj-neurovista`` was observed running on ``spartan`` (tmux
session confirmed) while the hub displayed it as ``mba``. Root cause
was two-fold:

1. Client-side: ``resolve_machine_label()`` (Python) and the
   ``connection.ts`` / ``heartbeat.ts`` (TS) heartbeat builders
   prioritised ``$SCITEX_OROCHI_HOSTNAME`` / ``$SCITEX_OROCHI_MACHINE``
   env vars OVER the live ``hostname()`` call. A stale env var
   inherited into a spartan process (e.g. from a shared tmux env or
   sac launcher that originally ran on mba) would silently override
   the real host identity.

2. Hub-side: ``hub/registry/_payload.py::get_agents()`` never exposed
   the ``hostname`` field in the dashboard payload, so the frontend
   badge (``hostedAgentName``) always fell through to ``orochi_machine`` —
   meaning the lead's #257 work (capturing ``hostname`` distinct from
   ``orochi_machine``) was never reaching the UI.

The fix is "agents set their ``host`` field in heartbeat from their
own ``hostname()`` call, never from server-side auth/inference, and
the hub forwards that field unchanged to the dashboard."

These tests guard against regression on the hub-side half: an agent
that explicitly reports ``hostname="spartan"`` must surface as
``spartan`` in the dashboard payload REGARDLESS of which workspace
token authenticated the push (i.e. the hub must not derive host
identity from auth).
"""

import json

from django.test import Client, TestCase

from hub.models import Workspace, WorkspaceToken
from hub.registry import (
    _agents,
    get_agents,
    register_agent,
)


class ClientSuppliedHostnameTest(TestCase):
    """``register_agent`` accepts + round-trips the ``hostname`` field."""

    def setUp(self):
        _agents.clear()

    def test_hostname_round_trips_to_dashboard_payload(self):
        """When the client explicitly reports ``hostname="spartan"``,
        ``get_agents()`` exposes the same value — the payload
        assembler does NOT drop, rewrite, or derive it."""
        register_agent(
            "proj-neurovista",
            workspace_id=1,
            info={
                "orochi_machine": "spartan",
                "hostname": "spartan",
            },
        )
        rows = [a for a in get_agents(workspace_id=1) if a["name"] == "proj-neurovista"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hostname"], "spartan")
        self.assertEqual(rows[0]["orochi_machine"], "spartan")

    def test_hostname_distinct_from_machine_preserved(self):
        """When ``orochi_machine`` and ``hostname`` disagree (e.g. an agent
        whose YAML-config host label drifted from the live process
        host), the hub preserves both verbatim so the frontend can
        prefer the authoritative ``hostname`` signal.

        This is the direct regression case for the proj-neurovista
        bug: orochi_machine label might say ``mba`` (stale env) but
        hostname must report ``spartan`` because that's what the
        kernel said."""
        register_agent(
            "proj-neurovista",
            workspace_id=1,
            info={
                # Simulate the buggy client that reported the wrong
                # orochi_machine label due to env pollution.
                "orochi_machine": "mba",
                # And the live hostname the kernel actually returned.
                "hostname": "spartan",
            },
        )
        rows = [a for a in get_agents(workspace_id=1) if a["name"] == "proj-neurovista"]
        self.assertEqual(len(rows), 1)
        # Both fields round-trip verbatim — the hub never rewrites
        # either one based on auth or server-side inference.
        self.assertEqual(rows[0]["orochi_machine"], "mba")
        self.assertEqual(rows[0]["hostname"], "spartan")

    def test_hostname_missing_defaults_to_empty_string(self):
        """Legacy agents that never report ``hostname`` produce an
        empty string in the payload, not ``None`` — the frontend
        string-concatenation paths treat the two identically but
        JSON consumers may not."""
        register_agent(
            "legacy-agent",
            workspace_id=1,
            info={"orochi_machine": "mba"},
        )
        rows = [a for a in get_agents(workspace_id=1) if a["name"] == "legacy-agent"]
        self.assertEqual(rows[0]["hostname"], "")
        self.assertEqual(rows[0]["orochi_machine"], "mba")


class HostnameFromRestPushTest(TestCase):
    """``POST /api/agents/register/`` honours client-supplied ``hostname``
    regardless of which workspace token authenticated the request.

    This is the *auth-independence* half of the fix: the hub must not
    infer host identity from the token / user / IP. Two different
    tokens pushing for the same agent with explicit host fields must
    get exactly the host they asked for.
    """

    def setUp(self):
        self.client = Client()
        self.ws = Workspace.objects.create(name="host-identity-ws")
        # Two tokens in the same workspace — mimic "mba creds" and
        # "spartan creds" (or any cross-host cred situation).
        self.token_a = WorkspaceToken.objects.create(
            workspace=self.ws, label="mba-token"
        )
        self.token_b = WorkspaceToken.objects.create(
            workspace=self.ws, label="spartan-token"
        )
        _agents.clear()

    def _post(self, token, payload):
        body = dict(payload, token=token)
        return self.client.post(
            "/api/agents/register/",
            data=json.dumps(body),
            content_type="application/json",
        )

    def test_hostname_recorded_verbatim_from_client(self):
        """Client says ``hostname=spartan`` — hub records ``spartan``."""
        resp = self._post(
            self.token_a.token,
            {
                "name": "proj-neurovista",
                "orochi_machine": "spartan",
                "hostname": "spartan",
            },
        )
        self.assertEqual(resp.status_code, 200)
        rows = [
            a for a in get_agents(workspace_id=self.ws.id)
            if a["name"] == "proj-neurovista"
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hostname"], "spartan")
        self.assertEqual(rows[0]["orochi_machine"], "spartan")

    def test_hostname_not_inferred_from_token(self):
        """The auth token DOES NOT set the host identity.

        Simulates the proj-neurovista scenario: a process running on
        spartan reports ``hostname=spartan`` but happens to authenticate
        with a workspace token that was originally minted for mba (cred-
        copying side effect). The recorded host must be ``spartan``
        — what the client said — not anything derived from the token.
        """
        resp = self._post(
            # Authenticate with the "mba" token...
            self.token_a.token,
            {
                "name": "proj-neurovista",
                # ...but report the real host from the live process.
                "orochi_machine": "spartan",
                "hostname": "spartan",
            },
        )
        self.assertEqual(resp.status_code, 200)
        rows = [
            a for a in get_agents(workspace_id=self.ws.id)
            if a["name"] == "proj-neurovista"
        ]
        self.assertEqual(rows[0]["hostname"], "spartan")
        # And the ``orochi_machine`` YAML label the client sent is also kept
        # verbatim — the hub does not rewrite either field.
        self.assertEqual(rows[0]["orochi_machine"], "spartan")

    def test_hostname_persists_across_reregisters_via_different_tokens(self):
        """Two sequential pushes with different tokens must both
        honour the client-supplied host — the second push doesn't
        reset the field to something auth-derived."""
        self._post(
            self.token_a.token,
            {
                "name": "proj-neurovista",
                "orochi_machine": "spartan",
                "hostname": "spartan",
            },
        )
        # A second heartbeat arrives — same host, different token
        # (e.g. the fleet rotated tokens mid-run).
        self._post(
            self.token_b.token,
            {
                "name": "proj-neurovista",
                "orochi_machine": "spartan",
                "hostname": "spartan",
            },
        )
        rows = [
            a for a in get_agents(workspace_id=self.ws.id)
            if a["name"] == "proj-neurovista"
        ]
        self.assertEqual(rows[0]["hostname"], "spartan")

    def test_hostname_omitted_preserved_across_reregister(self):
        """A heartbeat that omits ``hostname`` must NOT wipe a
        previously-captured value. Matches the prev-preserve pattern
        already used for the rest of the #257 metadata fields."""
        self._post(
            self.token_a.token,
            {
                "name": "proj-neurovista",
                "orochi_machine": "spartan",
                "hostname": "spartan",
            },
        )
        # Legacy client that doesn't know about ``hostname``.
        self._post(
            self.token_a.token,
            {
                "name": "proj-neurovista",
                "orochi_machine": "spartan",
            },
        )
        rows = [
            a for a in get_agents(workspace_id=self.ws.id)
            if a["name"] == "proj-neurovista"
        ]
        self.assertEqual(rows[0]["hostname"], "spartan")
