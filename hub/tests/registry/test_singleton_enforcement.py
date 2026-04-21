"""Tests for #255 — singleton cardinality enforcement at the hub.

Background: #257 added ``instance_id`` (UUID per process) and
``start_ts_unix`` (epoch float) to the heartbeat metadata so the hub
could distinguish two processes claiming the same ``SCITEX_OROCHI_AGENT``
name. #255 then turns that data into an enforcement: when two WS
connections claim the same agent, the hub picks ONE winner (older
``start_ts_unix`` wins) and disconnects the OTHER with WebSocket close
code 4409 / reason ``duplicate_identity``.

These tests pin the decision rule, the conflict-event ring buffer, the
heartbeat-survival contract for the winner, and the detail-API surface
the dashboard reads to render the warning banner.

Backwards compatibility: legacy clients that don't report
``instance_id`` (older agent_meta.py installs) MUST keep working — the
hub falls back to the pre-#255 permissive multi-connection behaviour
with a logged WARNING (no enforcement, no eviction).
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

from django.test import Client, TestCase

from hub.models import Workspace, WorkspaceToken
from hub.registry import (
    SINGLETON_EVENT_WINDOW_S,
    _agents,
    _connection_identity,
    _connections,
    _singleton_events,
    decide_singleton_winner,
    get_recent_singleton_event,
    list_sibling_channels,
    record_singleton_conflict,
    register_agent,
    register_connection,
    set_connection_identity,
    update_heartbeat,
)


def _reset_registry() -> None:
    _agents.clear()
    _connections.clear()
    _connection_identity.clear()
    _singleton_events.clear()


class DecideSingletonWinnerTests(TestCase):
    """Pure-function tests for the decision rule — no Django, no async."""

    def test_older_start_ts_wins(self):
        """Case (a) from the spec: two registers with different start_ts
        — the OLDER ``start_ts_unix`` wins."""
        # Incumbent older → incumbent keeps the claim.
        outcome = decide_singleton_winner(
            incumbent_instance_id="aaa",
            incumbent_start_ts_unix=1000.0,
            challenger_instance_id="bbb",
            challenger_start_ts_unix=2000.0,
        )
        self.assertEqual(outcome, "incumbent")

    def test_challenger_wins_when_older(self):
        """Symmetric case: when the challenger is older, the incumbent
        is evicted (a faster-restarting sibling shouldn't be able to
        steal the claim from the original process by reconnecting)."""
        outcome = decide_singleton_winner(
            incumbent_instance_id="aaa",
            incumbent_start_ts_unix=2000.0,
            challenger_instance_id="bbb",
            challenger_start_ts_unix=1000.0,
        )
        self.assertEqual(outcome, "challenger")

    def test_tie_keeps_incumbent(self):
        """Case (b): equal ``start_ts_unix`` — incumbent wins.

        Don't disrupt the running process when the tiebreaker is
        ambiguous; both halves of the race are equally fresh.
        """
        outcome = decide_singleton_winner(
            incumbent_instance_id="aaa",
            incumbent_start_ts_unix=1000.0,
            challenger_instance_id="bbb",
            challenger_start_ts_unix=1000.0,
        )
        self.assertEqual(outcome, "incumbent")

    def test_legacy_missing_instance_id_keeps_incumbent(self):
        """Case (c): legacy clients without ``instance_id`` — no
        enforcement (incumbent wins, caller must allow both)."""
        # Challenger is legacy.
        self.assertEqual(
            decide_singleton_winner("aaa", 1000.0, "", 999.0),
            "incumbent",
        )
        # Incumbent is legacy.
        self.assertEqual(
            decide_singleton_winner("", 1000.0, "bbb", 999.0),
            "incumbent",
        )
        # Both legacy.
        self.assertEqual(
            decide_singleton_winner("", None, "", None),
            "incumbent",
        )

    def test_same_instance_id_is_not_a_conflict(self):
        """Same ``instance_id`` from both sides means the same process
        re-registered after a transient WS reconnect — not a singleton
        race. Decision: incumbent (caller treats it as a no-op, no
        eviction)."""
        outcome = decide_singleton_winner(
            incumbent_instance_id="same-uuid",
            incumbent_start_ts_unix=1000.0,
            challenger_instance_id="same-uuid",
            challenger_start_ts_unix=1500.0,
        )
        self.assertEqual(outcome, "incumbent")

    def test_missing_start_ts_keeps_incumbent(self):
        """If one side has ``instance_id`` but not ``start_ts_unix`` we
        can't strictly tiebreak — incumbent wins to protect the running
        process."""
        outcome = decide_singleton_winner(
            incumbent_instance_id="aaa",
            incumbent_start_ts_unix=None,
            challenger_instance_id="bbb",
            challenger_start_ts_unix=2000.0,
        )
        self.assertEqual(outcome, "incumbent")
        outcome = decide_singleton_winner(
            incumbent_instance_id="aaa",
            incumbent_start_ts_unix=1000.0,
            challenger_instance_id="bbb",
            challenger_start_ts_unix=None,
        )
        self.assertEqual(outcome, "incumbent")


class ConnectionIdentityTrackingTests(TestCase):
    """Per-channel identity map (used by the register handler to find
    siblings)."""

    def setUp(self):
        _reset_registry()

    def test_set_and_list_sibling_channels(self):
        set_connection_identity("ch-1", "head-mba", "uuid-1", 1000.0)
        set_connection_identity("ch-2", "head-mba", "uuid-2", 1500.0)
        # An unrelated agent on a third channel — must NOT show up
        # when we ask for head-mba siblings.
        set_connection_identity("ch-3", "head-spartan", "uuid-3", 1000.0)
        sibs = list_sibling_channels("head-mba", exclude="ch-1")
        self.assertEqual(len(sibs), 1)
        self.assertEqual(sibs[0]["channel_name"], "ch-2")
        self.assertEqual(sibs[0]["instance_id"], "uuid-2")
        self.assertEqual(sibs[0]["start_ts_unix"], 1500.0)

    def test_clear_drops_entry(self):
        from hub.registry import clear_connection_identity

        set_connection_identity("ch-1", "head-mba", "uuid-1", 1000.0)
        clear_connection_identity("ch-1")
        self.assertEqual(list_sibling_channels("head-mba"), [])

    def test_set_with_empty_args_is_noop(self):
        set_connection_identity("", "head-mba", "uuid-1", 1000.0)
        set_connection_identity("ch-1", "", "uuid-1", 1000.0)
        self.assertEqual(list_sibling_channels("head-mba"), [])


class SingletonConflictRingBufferTests(TestCase):
    """Bounded conflict-event buffer + per-agent recent lookup."""

    def setUp(self):
        _reset_registry()

    def test_record_and_get_recent_event(self):
        record_singleton_conflict(
            name="head-mba",
            winner_instance_id="aaa",
            loser_instance_id="bbb",
            winner_start_ts_unix=1000.0,
            loser_start_ts_unix=2000.0,
            outcome="incumbent",
        )
        ev = get_recent_singleton_event("head-mba")
        self.assertIsNotNone(ev)
        self.assertEqual(ev["winner_instance_id"], "aaa")
        self.assertEqual(ev["loser_instance_id"], "bbb")
        self.assertEqual(ev["outcome"], "incumbent")
        # Newer events for the same agent supersede older ones.
        record_singleton_conflict(
            name="head-mba",
            winner_instance_id="ccc",
            loser_instance_id="ddd",
            outcome="challenger",
        )
        ev2 = get_recent_singleton_event("head-mba")
        self.assertEqual(ev2["winner_instance_id"], "ccc")
        self.assertEqual(ev2["outcome"], "challenger")

    def test_recent_event_filtered_by_window(self):
        """Events older than ``within_seconds`` MUST NOT be returned —
        the dashboard banner depends on this auto-fade."""
        record_singleton_conflict(
            name="head-mba",
            winner_instance_id="aaa",
            loser_instance_id="bbb",
        )
        # Backdate the event past the default window.
        _singleton_events[-1]["ts"] = time.time() - SINGLETON_EVENT_WINDOW_S - 1
        self.assertIsNone(get_recent_singleton_event("head-mba"))

    def test_recent_event_for_other_agent_is_none(self):
        record_singleton_conflict(
            name="head-mba",
            winner_instance_id="aaa",
            loser_instance_id="bbb",
        )
        self.assertIsNone(get_recent_singleton_event("head-spartan"))


class HeartbeatSurvivalForWinnerTests(TestCase):
    """Case (d): after a singleton race, the winner's heartbeat sequence
    must continue to update — the eviction must not corrupt the registry
    entry the winner is still using."""

    def setUp(self):
        _reset_registry()

    def test_winner_heartbeat_still_updates(self):
        # Incumbent registers as the winner.
        register_agent(
            "head-mba",
            workspace_id=1,
            info={
                "instance_id": "winner-uuid",
                "start_ts_unix": 1000.0,
                "machine": "mba",
            },
        )
        register_connection("head-mba", "ch-incumbent")
        set_connection_identity("ch-incumbent", "head-mba", "winner-uuid", 1000.0)
        # Conflict happens; record it (simulates _enforce_singleton).
        record_singleton_conflict(
            name="head-mba",
            winner_instance_id="winner-uuid",
            loser_instance_id="loser-uuid",
            winner_start_ts_unix=1000.0,
            loser_start_ts_unix=2000.0,
            outcome="incumbent",
        )
        # Winner sends a fresh heartbeat — the registry entry MUST
        # still be live (not blanked, not flipped to offline).
        before_ts = _agents["head-mba"]["last_heartbeat"]
        time.sleep(0.01)
        update_heartbeat("head-mba", {"cpu_count": 8})
        after_ts = _agents["head-mba"]["last_heartbeat"]
        self.assertGreater(after_ts, before_ts)
        self.assertEqual(_agents["head-mba"]["status"], "online")
        self.assertEqual(_agents["head-mba"]["instance_id"], "winner-uuid")


class AgentDetailApiSingletonEventTest(TestCase):
    """Case (e): the conflict event surfaces in the detail API.

    Mirrors the ``AgentDetailApiTest`` setup pattern: register an agent
    against a real Workspace + WorkspaceToken, then GET the detail
    endpoint and assert the new ``last_duplicate_identity_event`` key is
    populated when an event has happened, and ``None`` otherwise.
    """

    def setUp(self):
        _reset_registry()
        self.client = Client()
        self.ws = Workspace.objects.create(name="singleton-ws")
        self.token = WorkspaceToken.objects.create(
            workspace=self.ws, label="singleton-test"
        )

    def _register_alpha(self):
        register_agent(
            name="alpha",
            workspace_id=self.ws.id,
            info={
                "agent_id": "alpha",
                "machine": "MBA",
                "instance_id": "winner-uuid",
                "start_ts_unix": 1000.0,
            },
        )

    def _detail(self, name="alpha"):
        return self.client.get(
            f"/api/agents/{name}/detail/",
            data={"token": self.token.token},
        )

    def test_no_event_yields_null_field(self):
        self._register_alpha()
        resp = self._detail()
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("last_duplicate_identity_event", data)
        self.assertIsNone(data["last_duplicate_identity_event"])

    def test_recent_event_surfaces_with_canonical_shape(self):
        self._register_alpha()
        record_singleton_conflict(
            name="alpha",
            winner_instance_id="winner-uuid",
            loser_instance_id="loser-uuid",
            winner_start_ts_unix=1000.0,
            loser_start_ts_unix=2000.0,
            outcome="incumbent",
        )
        resp = self._detail()
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        ev = data["last_duplicate_identity_event"]
        self.assertIsNotNone(ev)
        self.assertEqual(ev["winner_instance_id"], "winner-uuid")
        self.assertEqual(ev["loser_instance_id"], "loser-uuid")
        self.assertEqual(ev["winner_start_ts_unix"], 1000.0)
        self.assertEqual(ev["loser_start_ts_unix"], 2000.0)
        self.assertEqual(ev["outcome"], "incumbent")
        self.assertIsNotNone(ev["ts"])
        self.assertIsNotNone(ev["ts_iso"])

    def test_aged_out_event_falls_back_to_null(self):
        self._register_alpha()
        record_singleton_conflict(
            name="alpha",
            winner_instance_id="winner-uuid",
            loser_instance_id="loser-uuid",
        )
        # Backdate beyond the window — the API MUST drop it.
        _singleton_events[-1]["ts"] = time.time() - SINGLETON_EVENT_WINDOW_S - 5
        resp = self._detail()
        self.assertIsNone(resp.json()["last_duplicate_identity_event"])


def _make_consumer(agent_name: str, channel_name: str):
    """Return a stub consumer with the attributes ``_enforce_singleton``
    accesses. Heavy use of ``MagicMock`` keeps the test off the Channels
    transport so the assertions stay focused on the hub-side decision
    + close path."""
    consumer = MagicMock()
    consumer.agent_name = agent_name
    consumer.channel_name = channel_name
    consumer.send_json = AsyncMock()
    consumer.close = AsyncMock()
    consumer.channel_layer = MagicMock()
    consumer.channel_layer.send = AsyncMock()
    return consumer


class EnforceSingletonHandlerTests(TestCase):
    """End-to-end exercise of ``_enforce_singleton`` from the
    register-frame path.

    Verifies:

      * older incumbent → challenger is closed; no agent_meta written;
      * older challenger → sibling is evicted; conflict recorded;
      * legacy incumbent (no instance_id) → no eviction (permissive
        fallback), challenger still proceeds.
    """

    def setUp(self):
        _reset_registry()

    def test_incumbent_wins_closes_challenger(self):
        from hub.consumers._agent_handlers import (
            DUPLICATE_IDENTITY_CLOSE_CODE,
            _enforce_singleton,
        )

        # Incumbent already registered with older start_ts.
        set_connection_identity(
            "ch-incumbent", "head-mba", "winner-uuid", 1000.0
        )
        register_connection("head-mba", "ch-incumbent")

        # Challenger arrives (newer start_ts → loses).
        challenger = _make_consumer("head-mba", "ch-challenger")
        closed = asyncio.run(
            _enforce_singleton(
                challenger,
                challenger_instance_id="loser-uuid",
                challenger_start_ts_unix=2000.0,
            )
        )
        self.assertTrue(closed)
        challenger.close.assert_awaited_once_with(
            code=DUPLICATE_IDENTITY_CLOSE_CODE
        )
        # Conflict event recorded with the right sides.
        ev = get_recent_singleton_event("head-mba")
        self.assertIsNotNone(ev)
        self.assertEqual(ev["winner_instance_id"], "winner-uuid")
        self.assertEqual(ev["loser_instance_id"], "loser-uuid")
        self.assertEqual(ev["outcome"], "incumbent")
        # Sibling was NOT evicted (incumbent stays).
        challenger.channel_layer.send.assert_not_awaited()

    def test_challenger_wins_evicts_sibling(self):
        from hub.consumers._agent_handlers import _enforce_singleton

        # Incumbent has NEWER start_ts → it loses.
        set_connection_identity(
            "ch-incumbent", "head-mba", "loser-uuid", 2000.0
        )
        register_connection("head-mba", "ch-incumbent")

        challenger = _make_consumer("head-mba", "ch-challenger")
        closed = asyncio.run(
            _enforce_singleton(
                challenger,
                challenger_instance_id="winner-uuid",
                challenger_start_ts_unix=1000.0,
            )
        )
        self.assertFalse(closed)
        challenger.close.assert_not_awaited()
        # Sibling channel was sent the eviction message.
        challenger.channel_layer.send.assert_awaited_once()
        args = challenger.channel_layer.send.await_args
        self.assertEqual(args.args[0], "ch-incumbent")
        self.assertEqual(args.args[1]["type"], "singleton.evict")
        # Conflict event recorded with challenger as the winner.
        ev = get_recent_singleton_event("head-mba")
        self.assertEqual(ev["winner_instance_id"], "winner-uuid")
        self.assertEqual(ev["loser_instance_id"], "loser-uuid")
        self.assertEqual(ev["outcome"], "challenger")

    def test_legacy_incumbent_no_eviction(self):
        """Legacy permissive mode: incumbent has no ``instance_id`` so
        the hub can't strictly enforce. The challenger MUST be allowed
        through (returns False) and NO eviction message is sent."""
        from hub.consumers._agent_handlers import _enforce_singleton

        # Incumbent is legacy (no instance_id reported).
        set_connection_identity("ch-incumbent", "head-mba", "", None)
        register_connection("head-mba", "ch-incumbent")

        challenger = _make_consumer("head-mba", "ch-challenger")
        closed = asyncio.run(
            _enforce_singleton(
                challenger,
                challenger_instance_id="new-uuid",
                challenger_start_ts_unix=1000.0,
            )
        )
        self.assertFalse(closed)
        challenger.close.assert_not_awaited()
        challenger.channel_layer.send.assert_not_awaited()
        # No conflict event recorded — legacy mode is observed via the
        # WARNING log only.
        self.assertIsNone(get_recent_singleton_event("head-mba"))

    def test_same_instance_id_is_not_a_conflict(self):
        """Same UUID from both sides: a transient reconnect of the same
        process. The new connection must register normally and no event
        must be recorded."""
        from hub.consumers._agent_handlers import _enforce_singleton

        set_connection_identity(
            "ch-incumbent", "head-mba", "same-uuid", 1000.0
        )
        register_connection("head-mba", "ch-incumbent")

        challenger = _make_consumer("head-mba", "ch-challenger")
        closed = asyncio.run(
            _enforce_singleton(
                challenger,
                challenger_instance_id="same-uuid",
                challenger_start_ts_unix=1500.0,
            )
        )
        self.assertFalse(closed)
        challenger.close.assert_not_awaited()
        challenger.channel_layer.send.assert_not_awaited()
        self.assertIsNone(get_recent_singleton_event("head-mba"))
