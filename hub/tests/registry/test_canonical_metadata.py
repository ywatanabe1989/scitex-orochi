"""Tests for #257 — canonical heartbeat runtime metadata.

Verifies that ``register_agent`` accepts the new fields (`hostname`,
`uname`, `instance_id`, `start_ts_unix`, `is_proxy`, `priority_rank`,
`priority_list`, `launch_method`, `heartbeat_seq`), preserves them
across re-registers when a heartbeat omits a field, and that they
flow through to the agent-detail API response.

Background: HANDOFF.md §3 #1 — every heartbeat WS frame must carry
truthful per-process metadata so the dashboard never displays a
fabricated `@host` label (the ghost-mba bug, #256). This is the
foundational PR — singleton enforcement (#255) and dynamic priority
ranking depend on these fields landing first.
"""

from django.test import TestCase

from hub.registry import (
    _agents,
    register_agent,
)


def get_agent(name: str) -> dict:
    """Local helper — the registry exposes _agents (a dict) but no
    public single-agent getter. Tests reach into _agents directly to
    keep the test signal focused on register_agent's behavior."""
    return _agents[name]


class CanonicalMetadataAcceptedTest(TestCase):
    """Each new metadata field round-trips through register_agent."""

    def setUp(self):
        # Tests share the in-memory _agents dict; ensure a clean slate.
        _agents.clear()

    def test_hostname_stored_separately_from_machine(self):
        """`machine` (YAML label) and `hostname` (live hostname(1)) are
        distinct — the dashboard must render the latter, not the former."""
        register_agent(
            "agent-x",
            workspace_id=1,
            info={
                "machine": "ywata-note-win",
                "hostname": "ywata-note-win",
            },
        )
        a = get_agent("agent-x")
        self.assertEqual(a["machine"], "ywata-note-win")
        self.assertEqual(a["hostname"], "ywata-note-win")

    def test_all_257_fields_round_trip(self):
        info = {
            "machine": "spartan",
            "hostname": "spartan",
            "uname": "Linux spartan 5.15.0 #1 SMP x86_64 GNU/Linux",
            "instance_id": "11111111-2222-3333-4444-555555555555",
            "start_ts_unix": 1734400000.0,
            "is_proxy": False,
            "priority_rank": 0,
            "priority_list": ["spartan", "ywata-note-win", "mba", "nas"],
            "launch_method": "sac",
            "heartbeat_seq": 1,
        }
        register_agent("proj-neurovista", workspace_id=1, info=info)
        a = get_agent("proj-neurovista")
        for k, v in info.items():
            self.assertEqual(a[k], v, f"field {k!r} did not round-trip")

    def test_omitted_fields_preserved_across_reregisters(self):
        """A heartbeat that omits a field must NOT wipe the previous
        value — older clients gradually upgrade and the LEDs / detail
        pane shouldn't flicker on each re-register cycle.
        Mirrors the prev-preserve pitfall already documented in
        ``register_agent``."""
        register_agent(
            "proj-neurovista",
            workspace_id=1,
            info={
                "machine": "spartan",
                "hostname": "spartan",
                "instance_id": "abc",
                "start_ts_unix": 1234.5,
                "is_proxy": False,
                "priority_rank": 0,
                "priority_list": ["spartan", "ywata-note-win"],
                "launch_method": "sac",
                "heartbeat_seq": 5,
                "uname": "Linux spartan 5.15.0",
            },
        )
        # Simulate a legacy heartbeat that knows nothing about #257.
        register_agent(
            "proj-neurovista",
            workspace_id=1,
            info={"machine": "spartan"},
        )
        a = get_agent("proj-neurovista")
        self.assertEqual(a["hostname"], "spartan")
        self.assertEqual(a["instance_id"], "abc")
        self.assertEqual(a["start_ts_unix"], 1234.5)
        self.assertFalse(a["is_proxy"])
        self.assertEqual(a["priority_rank"], 0)
        self.assertEqual(a["priority_list"], ["spartan", "ywata-note-win"])
        self.assertEqual(a["launch_method"], "sac")
        self.assertEqual(a["heartbeat_seq"], 5)
        self.assertEqual(a["uname"], "Linux spartan 5.15.0")

    def test_legacy_clients_default_safely(self):
        """An agent that never reports the new fields produces sensible
        defaults — empty strings for textual fields, False for bools,
        None for numerics, [] for the priority list, 0 for the seq."""
        register_agent(
            "legacy-agent",
            workspace_id=1,
            info={"machine": "ywata-note-win"},
        )
        a = get_agent("legacy-agent")
        self.assertEqual(a["hostname"], "")
        self.assertEqual(a["uname"], "")
        self.assertEqual(a["instance_id"], "")
        self.assertIsNone(a["start_ts_unix"])
        self.assertFalse(a["is_proxy"])
        self.assertIsNone(a["priority_rank"])
        self.assertEqual(a["priority_list"], [])
        self.assertEqual(a["launch_method"], "")
        self.assertEqual(a["heartbeat_seq"], 0)

    def test_is_proxy_bool_coercion(self):
        """`is_proxy` must always come out a bool — heartbeats that
        send the field as a truthy/falsy non-bool (legacy JSON shape)
        are coerced rather than passed through."""
        register_agent(
            "agent-trueish", workspace_id=1, info={"is_proxy": 1}
        )
        register_agent(
            "agent-falseish", workspace_id=1, info={"is_proxy": 0}
        )
        self.assertIs(get_agent("agent-trueish")["is_proxy"], True)
        self.assertIs(get_agent("agent-falseish")["is_proxy"], False)

    def test_priority_list_invalid_type_falls_back_to_prev(self):
        """A heartbeat that sends `priority_list` as a non-list (e.g.
        a string) must NOT crash and must NOT corrupt the stored
        list — fall back to the previous value."""
        register_agent(
            "agent-y",
            workspace_id=1,
            info={"priority_list": ["spartan", "mba"]},
        )
        register_agent(
            "agent-y",
            workspace_id=1,
            info={"priority_list": "not-a-list"},
        )
        self.assertEqual(get_agent("agent-y")["priority_list"], ["spartan", "mba"])

    def test_start_ts_unix_zero_is_preserved(self):
        """Defensive: 0.0 is a valid timestamp (epoch). Don't let
        `or` coerce it back to the previous value."""
        register_agent(
            "agent-z",
            workspace_id=1,
            info={"start_ts_unix": 0.0},
        )
        self.assertEqual(get_agent("agent-z")["start_ts_unix"], 0.0)

    def test_new_instance_id_overwrites_prev(self):
        """A different instance_id from a heartbeat means a different
        process is now claiming the name (singleton race or fast
        restart). The newer ID wins — the hub should also flag the
        event as a singleton conflict, but that's #255 (separate PR)."""
        register_agent(
            "racy", workspace_id=1, info={"instance_id": "first"}
        )
        register_agent(
            "racy", workspace_id=1, info={"instance_id": "second"}
        )
        self.assertEqual(get_agent("racy")["instance_id"], "second")
