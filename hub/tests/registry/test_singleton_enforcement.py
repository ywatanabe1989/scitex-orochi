"""Tests for #255 — singleton cardinality enforcement at the hub.

Verifies the registry-level decision algorithm and the agent-detail
API surface. The WS-level enforcement (close-frame on the loser, evict
event for the incumbent) is exercised at the consumer level in the
consumer test suite; here we pin the decision algorithm and the
event-buffer / detail-payload contract so regressions in the policy
are caught even if the consumer wiring is later refactored.

Algorithm under test (HANDOFF.md §3 #3 + ywatanabe msg #14757):

  * Two registers with full identity → older ``start_ts_unix`` wins.
  * Tie or missing identity → incumbent wins (no disruption on
    insufficient evidence) / no enforcement (legacy clients).
  * The conflict event surfaces in ``/api/agents/<name>/detail/`` as
    ``last_duplicate_identity_event``.
"""

import time

from django.test import Client, TestCase

from hub.models import Workspace, WorkspaceToken


class _RegistryReset:
    """Mixin that wipes all registry state between tests.

    Singleton enforcement state lives across four module-level dicts
    (``_agents``, ``_connections``, ``_connection_identity``,
    ``_singleton_events``); without a clean slate per test, an event
    recorded in test A leaks into test B's detail-API assertion.
    """

    def setUp(self):
        super().setUp()
        from hub.registry import (
            _agents,
            _connection_identity,
            _connections,
            _singleton_events,
        )

        _agents.clear()
        _connections.clear()
        _connection_identity.clear()
        _singleton_events.clear()


class DecideSingletonWinnerTest(_RegistryReset, TestCase):
    """Pin :func:`hub.registry.decide_singleton_winner` policy."""

    def test_first_connection_no_enforcement(self):
        """No incumbent → no-enforcement (the new WS just registers)."""
        from hub.registry import decide_singleton_winner

        decision = decide_singleton_winner(
            "agent-x",
            new_instance_id="iid-1",
            new_start_ts_unix=1000.0,
        )
        self.assertEqual(decision, "no_enforcement")

    def test_older_start_ts_wins_even_when_challenger_arrives_later(self):
        """Two registers, both have full identity → older start_ts wins.

        The original process started at ``t=1000`` and connected first;
        a second process with ``start_ts=2000`` later races onto the same
        agent name. The original (incumbent) is older → it wins, the
        challenger should be closed.
        """
        from hub.registry import (
            decide_singleton_winner,
            register_connection,
            set_connection_identity,
        )

        # Incumbent: started first, connected first.
        set_connection_identity("conn-incumbent", "agent-x", "iid-old", 1000.0)
        register_connection("agent-x", "conn-incumbent")

        # Challenger: started later (newer process).
        decision = decide_singleton_winner(
            "agent-x",
            new_instance_id="iid-new",
            new_start_ts_unix=2000.0,
        )
        self.assertEqual(decision, "incumbent")

    def test_older_challenger_wins_against_newer_incumbent(self):
        """If the challenger has the OLDER start_ts (e.g. an original
        process reconnects after the hub temporarily had a younger
        racer), the challenger wins and the incumbent gets evicted."""
        from hub.registry import (
            decide_singleton_winner,
            register_connection,
            set_connection_identity,
        )

        # A young racer is the current incumbent.
        set_connection_identity("conn-young", "agent-x", "iid-young", 2000.0)
        register_connection("agent-x", "conn-young")

        # The original older process reconnects.
        decision = decide_singleton_winner(
            "agent-x",
            new_instance_id="iid-original",
            new_start_ts_unix=1000.0,
        )
        self.assertEqual(decision, "challenger")

    def test_tie_falls_to_incumbent(self):
        """Equal ``start_ts_unix`` → incumbent keeps the claim (don't
        disrupt a healthy connection on insufficient evidence)."""
        from hub.registry import (
            decide_singleton_winner,
            register_connection,
            set_connection_identity,
        )

        set_connection_identity("conn-A", "agent-x", "iid-A", 1500.0)
        register_connection("agent-x", "conn-A")

        decision = decide_singleton_winner(
            "agent-x",
            new_instance_id="iid-B",
            new_start_ts_unix=1500.0,
        )
        self.assertEqual(decision, "incumbent")

    def test_missing_challenger_identity_no_enforcement(self):
        """Legacy challenger that omits ``instance_id`` / ``start_ts_unix``
        → no enforcement (back-compat: the agent keeps working)."""
        from hub.registry import (
            decide_singleton_winner,
            register_connection,
            set_connection_identity,
        )

        set_connection_identity("conn-A", "agent-x", "iid-A", 1500.0)
        register_connection("agent-x", "conn-A")

        # Challenger has no identity (legacy client).
        self.assertEqual(
            decide_singleton_winner("agent-x", "", None),
            "no_enforcement",
        )
        self.assertEqual(
            decide_singleton_winner("agent-x", "iid-X", None),
            "no_enforcement",
        )
        self.assertEqual(
            decide_singleton_winner("agent-x", "", 1.0),
            "no_enforcement",
        )

    def test_missing_incumbent_identity_no_enforcement(self):
        """Legacy incumbent (full identity not recorded) → no
        enforcement; we don't disrupt an in-flight connection just
        because the hub doesn't have its boot metadata."""
        from hub.registry import (
            decide_singleton_winner,
            register_connection,
            set_connection_identity,
        )

        # Incumbent has no instance_id (legacy WS that connected before
        # #257 / #255 landed).
        set_connection_identity("conn-A", "agent-x", "", None)
        register_connection("agent-x", "conn-A")

        decision = decide_singleton_winner(
            "agent-x",
            new_instance_id="iid-new",
            new_start_ts_unix=2000.0,
        )
        self.assertEqual(decision, "no_enforcement")


class SingletonEventBufferTest(_RegistryReset, TestCase):
    """Pin the per-agent event ring buffer behaviour."""

    def test_record_then_get_recent(self):
        from hub.registry import (
            get_recent_singleton_event,
            record_singleton_conflict,
        )

        self.assertIsNone(get_recent_singleton_event("agent-x"))

        record_singleton_conflict(
            "agent-x",
            winner_instance_id="iid-W",
            loser_instance_id="iid-L",
        )
        evt = get_recent_singleton_event("agent-x")
        self.assertIsNotNone(evt)
        self.assertEqual(evt["winner_instance_id"], "iid-W")
        self.assertEqual(evt["loser_instance_id"], "iid-L")
        self.assertEqual(evt["reason"], "duplicate_identity")
        self.assertAlmostEqual(evt["ts"], time.time(), delta=5.0)

    def test_returns_newest_event(self):
        from hub.registry import (
            get_recent_singleton_event,
            record_singleton_conflict,
        )

        record_singleton_conflict("agent-x", "iid-1", "iid-A")
        time.sleep(0.01)
        record_singleton_conflict("agent-x", "iid-2", "iid-B")
        evt = get_recent_singleton_event("agent-x")
        self.assertEqual(evt["winner_instance_id"], "iid-2")
        self.assertEqual(evt["loser_instance_id"], "iid-B")

    def test_stale_events_pruned(self):
        """Events older than ``SINGLETON_EVENT_WINDOW_S`` are dropped on
        read so a long-running hub never returns ancient history."""
        from hub.registry import (
            SINGLETON_EVENT_WINDOW_S,
            _singleton_events,
            get_recent_singleton_event,
        )

        # Inject a stale event by hand (older than the window).
        stale_ts = time.time() - (SINGLETON_EVENT_WINDOW_S + 60)
        _singleton_events["agent-x"] = [
            {
                "ts": stale_ts,
                "agent": "agent-x",
                "winner_instance_id": "iid-stale-W",
                "loser_instance_id": "iid-stale-L",
                "reason": "duplicate_identity",
            }
        ]
        self.assertIsNone(get_recent_singleton_event("agent-x"))


class SingletonHeartbeatSurvivalTest(_RegistryReset, TestCase):
    """The winner survives a typical heartbeat sequence — a regression
    guard ensuring later heartbeats don't re-trigger enforcement on
    the very connection that just won the race."""

    def test_winner_survives_heartbeat_sequence(self):
        from hub.registry import (
            decide_singleton_winner,
            register_agent,
            register_connection,
            set_connection_identity,
            update_heartbeat,
        )

        # Incumbent is older → it wins the singleton race.
        set_connection_identity("conn-incumbent", "agent-x", "iid-old", 1000.0)
        register_connection("agent-x", "conn-incumbent")
        register_agent(
            "agent-x",
            workspace_id=1,
            info={"instance_id": "iid-old", "start_ts_unix": 1000.0},
        )

        # A few heartbeats from the same incumbent (same identity).
        for _ in range(3):
            update_heartbeat("agent-x", {"cpu_count": 4})

        # Now a young racer challenges. Decision should still favour the
        # older incumbent — its identity is intact in the per-channel
        # table even after the heartbeats.
        decision = decide_singleton_winner(
            "agent-x",
            new_instance_id="iid-young",
            new_start_ts_unix=2000.0,
        )
        self.assertEqual(decision, "incumbent")


class ConnectionIdentityLifecycleTest(_RegistryReset, TestCase):
    """Pin set/get/clear of per-channel identity rows."""

    def test_set_then_get(self):
        from hub.registry import (
            get_connection_identity,
            set_connection_identity,
        )

        set_connection_identity("ch-1", "agent-x", "iid-1", 1234.5)
        ident = get_connection_identity("ch-1")
        self.assertIsNotNone(ident)
        self.assertEqual(ident["agent_name"], "agent-x")
        self.assertEqual(ident["instance_id"], "iid-1")
        self.assertEqual(ident["start_ts_unix"], 1234.5)

    def test_clear_drops_identity(self):
        from hub.registry import (
            clear_connection_identity,
            get_connection_identity,
            set_connection_identity,
        )

        set_connection_identity("ch-1", "agent-x", "iid-1", 1234.5)
        clear_connection_identity("ch-1")
        self.assertIsNone(get_connection_identity("ch-1"))

    def test_list_sibling_channels(self):
        from hub.registry import (
            list_sibling_channels,
            register_connection,
            set_connection_identity,
        )

        # Two siblings under one name.
        set_connection_identity("ch-A", "agent-x", "iid-A", 1.0)
        set_connection_identity("ch-B", "agent-x", "iid-B", 2.0)
        register_connection("agent-x", "ch-A")
        register_connection("agent-x", "ch-B")

        siblings = list_sibling_channels("agent-x")
        self.assertEqual(set(siblings), {"ch-A", "ch-B"})
        self.assertEqual(list_sibling_channels("agent-y"), [])


class DetailApiSurfacesEventTest(_RegistryReset, TestCase):
    """``/api/agents/<name>/detail/`` exposes the most recent singleton
    conflict via ``last_duplicate_identity_event``."""

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.ws = Workspace.objects.create(name="dup-ws")
        self.token = WorkspaceToken.objects.create(
            workspace=self.ws, label="dup-test"
        )

    def _register_agent(self):
        from hub.registry import register_agent

        register_agent(
            "alpha",
            workspace_id=self.ws.id,
            info={
                "machine": "MBA",
                "instance_id": "iid-current",
                "start_ts_unix": 1000.0,
            },
        )

    def _detail(self, name="alpha"):
        return self.client.get(
            f"/api/agents/{name}/detail/",
            data={"token": self.token.token},
        )

    def test_no_event_returns_null(self):
        self._register_agent()
        data = self._detail().json()
        self.assertIn("last_duplicate_identity_event", data)
        self.assertIsNone(data["last_duplicate_identity_event"])

    def test_event_surfaces_after_conflict(self):
        from hub.registry import record_singleton_conflict

        self._register_agent()
        record_singleton_conflict(
            "alpha",
            winner_instance_id="iid-current",
            loser_instance_id="iid-evicted",
        )
        data = self._detail().json()
        evt = data["last_duplicate_identity_event"]
        self.assertIsNotNone(evt)
        self.assertEqual(evt["winner_instance_id"], "iid-current")
        self.assertEqual(evt["loser_instance_id"], "iid-evicted")
        self.assertEqual(evt["reason"], "duplicate_identity")
        self.assertIn("ts", evt)


class LegacyClientCompatibilityTest(_RegistryReset, TestCase):
    """Back-compat: a legacy client that never reports
    ``instance_id`` / ``start_ts_unix`` MUST keep working — no
    enforcement, no event recorded, no surprise close-frame.
    """

    def test_legacy_only_no_event_recorded(self):
        from hub.registry import (
            decide_singleton_winner,
            get_recent_singleton_event,
            register_connection,
            set_connection_identity,
        )

        # Two legacy clients connect under the same name. Neither has
        # identity. The decider must say "no_enforcement" both times.
        set_connection_identity("ch-legacy-A", "agent-legacy", "", None)
        register_connection("agent-legacy", "ch-legacy-A")

        self.assertEqual(
            decide_singleton_winner("agent-legacy", "", None),
            "no_enforcement",
        )
        # And no event was recorded by the decider itself (the consumer
        # is responsible for recording when it actually evicts; the
        # decider is read-only).
        self.assertIsNone(get_recent_singleton_event("agent-legacy"))
