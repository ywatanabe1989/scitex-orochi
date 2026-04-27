"""Tests for todo#272 — proactive quota pressure detection + escalation.

Covers three layers:

1. :func:`_classify` — threshold → state mapping for the 5h / 7d
   windows (warn at 0.80 / 0.85, escalate at 0.95).
2. :func:`evaluate` — the per-heartbeat state-orochi_machine transitions:
   ok→warn posts to ``#progress``, warn→escalate posts to
   ``#escalation`` + ``#ywatanabe``, escalate→ok posts recovery,
   other transitions are silent (no spam on partial recovery /
   downshift per ywatanabe msg#7788).
3. :func:`check_agent_quota_pressure` — the heartbeat-hot-path entry
   point that reads the registry, runs :func:`evaluate`, and writes
   the new state back. The test doubles exercise the integration via
   ``register_agent`` + ``update_heartbeat`` (the same call chain the
   REST / WS handlers use) to prove end-to-end wiring.

Regression anchors:

- Prev-preserve of ``quota_state_5h`` / ``quota_state_7d`` across
  re-registers — without it, every heartbeat resets to ``ok`` and
  re-posts the warn / escalate message (spam).
- Silent downshift: escalate→warn must NOT post.
- Percentage input (0..100) is accepted as well as fractional (0..1)
  so the consumer doesn't misfire when producers use either
  convention.
"""

from __future__ import annotations

from django.test import TestCase

from hub.quota_watch import (
    ESCALATE_5H,
    ESCALATE_7D,
    STATE_ESCALATE,
    STATE_OK,
    STATE_WARN,
    WARN_5H,
    WARN_7D,
    _classify,
    _coerce_utilization,
    check_agent_quota_pressure,
    evaluate,
)
from hub.registry import _agents, register_agent, update_heartbeat


class ClassifyTest(TestCase):
    """Pure threshold classification."""

    def test_5h_boundaries(self):
        self.assertEqual(_classify(0.0, "5h"), STATE_OK)
        self.assertEqual(_classify(WARN_5H - 0.01, "5h"), STATE_OK)
        self.assertEqual(_classify(WARN_5H, "5h"), STATE_WARN)
        self.assertEqual(_classify(0.90, "5h"), STATE_WARN)
        self.assertEqual(_classify(ESCALATE_5H, "5h"), STATE_ESCALATE)
        self.assertEqual(_classify(1.0, "5h"), STATE_ESCALATE)

    def test_7d_boundaries(self):
        self.assertEqual(_classify(0.0, "7d"), STATE_OK)
        self.assertEqual(_classify(WARN_7D - 0.01, "7d"), STATE_OK)
        self.assertEqual(_classify(WARN_7D, "7d"), STATE_WARN)
        self.assertEqual(_classify(0.92, "7d"), STATE_WARN)
        self.assertEqual(_classify(ESCALATE_7D, "7d"), STATE_ESCALATE)

    def test_none_utilization_falls_back_to_ok(self):
        self.assertEqual(_classify(None, "5h"), STATE_OK)
        self.assertEqual(_classify(None, "7d"), STATE_OK)


class CoerceUtilizationTest(TestCase):
    """Producers may push 0..1 or 0..100; accept both."""

    def test_fraction_passthrough(self):
        self.assertAlmostEqual(_coerce_utilization(0.82), 0.82)
        self.assertAlmostEqual(_coerce_utilization(0.95), 0.95)

    def test_percentage_rescaled(self):
        self.assertAlmostEqual(_coerce_utilization(82), 0.82)
        self.assertAlmostEqual(_coerce_utilization(95.0), 0.95)

    def test_none_and_garbage_return_none(self):
        self.assertIsNone(_coerce_utilization(None))
        self.assertIsNone(_coerce_utilization(""))
        self.assertIsNone(_coerce_utilization("nan-value"))

    def test_negative_clamped_to_zero(self):
        self.assertEqual(_coerce_utilization(-0.01), 0.0)


class EvaluateStateMachineTest(TestCase):
    """Transition rules for the per-(agent, window) state orochi_machine."""

    def setUp(self):
        self.posts: list[tuple[str, str]] = []

    def _post(self, channel: str, text: str) -> None:
        self.posts.append((channel, text))

    def test_ok_to_warn_posts_progress(self):
        new_5h, new_7d, emitted = evaluate(
            "agent-burn",
            util_5h=0.81,
            util_7d=None,
            reset_5h="2026-04-22T01:00:00Z",
            reset_7d=None,
            prev_state_5h=STATE_OK,
            prev_state_7d=STATE_OK,
            post=self._post,
        )
        self.assertEqual(new_5h, STATE_WARN)
        self.assertEqual(new_7d, STATE_OK)
        self.assertEqual(len(self.posts), 1)
        channel, text = self.posts[0]
        self.assertEqual(channel, "#progress")
        self.assertIn("agent-burn", text)
        self.assertIn("5h", text)
        self.assertIn("81%", text)

    def test_warn_to_escalate_posts_escalation_and_ywatanabe(self):
        new_5h, _, _ = evaluate(
            "agent-burn",
            util_5h=0.96,
            util_7d=None,
            reset_5h="2026-04-22T01:00:00Z",
            reset_7d=None,
            prev_state_5h=STATE_WARN,
            prev_state_7d=STATE_OK,
            post=self._post,
        )
        self.assertEqual(new_5h, STATE_ESCALATE)
        channels = [c for c, _ in self.posts]
        self.assertIn("#escalation", channels)
        self.assertIn("#ywatanabe", channels)
        # Every emitted message names the agent + quota window so the
        # recipient can act (account rotation, migration decision).
        for _, text in self.posts:
            self.assertIn("agent-burn", text)
            self.assertIn("ESCALATE", text)

    def test_ok_to_escalate_skips_warn_but_still_escalates(self):
        """If a heartbeat gap makes the agent jump straight from ok to
        escalate (e.g. 10-minute poll lands after a burst), we still
        escalate rather than silently dropping the transition."""
        new_5h, _, _ = evaluate(
            "agent-burst",
            util_5h=0.97,
            util_7d=None,
            reset_5h=None,
            reset_7d=None,
            prev_state_5h=STATE_OK,
            prev_state_7d=STATE_OK,
            post=self._post,
        )
        self.assertEqual(new_5h, STATE_ESCALATE)
        channels = [c for c, _ in self.posts]
        self.assertIn("#escalation", channels)
        self.assertIn("#ywatanabe", channels)

    def test_escalate_to_ok_posts_recovery(self):
        new_5h, _, _ = evaluate(
            "agent-burn",
            util_5h=0.05,
            util_7d=None,
            reset_5h=None,
            reset_7d=None,
            prev_state_5h=STATE_ESCALATE,
            prev_state_7d=STATE_OK,
            post=self._post,
        )
        self.assertEqual(new_5h, STATE_OK)
        self.assertEqual(len(self.posts), 1)
        channel, text = self.posts[0]
        self.assertEqual(channel, "#progress")
        self.assertIn("recovered", text)

    def test_escalate_to_warn_silent(self):
        """Partial recovery must not spam — only full recovery pings."""
        new_5h, _, _ = evaluate(
            "agent-burn",
            util_5h=0.85,
            util_7d=None,
            reset_5h=None,
            reset_7d=None,
            prev_state_5h=STATE_ESCALATE,
            prev_state_7d=STATE_OK,
            post=self._post,
        )
        self.assertEqual(new_5h, STATE_WARN)
        self.assertEqual(self.posts, [])

    def test_warn_to_ok_silent(self):
        """Downshift is silent — only escalate→ok triggers recovery ping."""
        new_5h, _, _ = evaluate(
            "agent-burn",
            util_5h=0.10,
            util_7d=None,
            reset_5h=None,
            reset_7d=None,
            prev_state_5h=STATE_WARN,
            prev_state_7d=STATE_OK,
            post=self._post,
        )
        self.assertEqual(new_5h, STATE_OK)
        self.assertEqual(self.posts, [])

    def test_same_state_no_posts(self):
        """Repeated polls within the same band must not re-fire."""
        new_5h, new_7d, emitted = evaluate(
            "agent-burn",
            util_5h=0.82,
            util_7d=0.86,
            reset_5h=None,
            reset_7d=None,
            prev_state_5h=STATE_WARN,
            prev_state_7d=STATE_WARN,
            post=self._post,
        )
        self.assertEqual(new_5h, STATE_WARN)
        self.assertEqual(new_7d, STATE_WARN)
        self.assertEqual(self.posts, [])
        self.assertEqual(emitted, [])

    def test_both_windows_fire_independently(self):
        """5h and 7d transitions are evaluated + posted independently."""
        new_5h, new_7d, _ = evaluate(
            "agent-burn",
            util_5h=0.82,  # ok -> warn
            util_7d=0.96,  # ok -> escalate
            reset_5h="2026-04-22T01:00:00Z",
            reset_7d="2026-04-28T01:00:00Z",
            prev_state_5h=STATE_OK,
            prev_state_7d=STATE_OK,
            post=self._post,
        )
        self.assertEqual(new_5h, STATE_WARN)
        self.assertEqual(new_7d, STATE_ESCALATE)
        channels = [c for c, _ in self.posts]
        # 5h: warn -> #progress
        self.assertIn("#progress", channels)
        # 7d: escalate -> #escalation + #ywatanabe
        self.assertIn("#escalation", channels)
        self.assertIn("#ywatanabe", channels)


class CheckAgentQuotaPressureWiringTest(TestCase):
    """End-to-end wiring: register_agent + update_heartbeat triggers
    :func:`check_agent_quota_pressure` with prev-preserve of the state
    across heartbeats."""

    def setUp(self):
        _agents.clear()
        self.posts: list[tuple[str, str]] = []

    def _post(self, channel: str, text: str) -> None:
        self.posts.append((channel, text))

    def _register(self, name: str, **extra) -> None:
        info = {
            "orochi_machine": "test-host",
            "role": "head",
        }
        info.update(extra)
        register_agent(name, workspace_id=1, info=info)

    def test_unknown_agent_is_noop(self):
        check_agent_quota_pressure("missing-agent", post=self._post)
        self.assertEqual(self.posts, [])

    def test_missing_quota_fields_noop(self):
        self._register("agent-a")
        check_agent_quota_pressure("agent-a", post=self._post)
        self.assertEqual(self.posts, [])
        self.assertEqual(_agents["agent-a"].get("quota_state_5h"), STATE_OK)

    def test_first_warn_crossing_posts_once(self):
        self._register(
            "agent-a",
            quota_5h_used_pct=0.82,
            quota_5h_reset_at="2026-04-22T01:00:00Z",
        )
        check_agent_quota_pressure("agent-a", post=self._post)
        self.assertEqual(_agents["agent-a"]["quota_state_5h"], STATE_WARN)
        channels = [c for c, _ in self.posts]
        self.assertEqual(channels.count("#progress"), 1)

    def test_repeat_poll_same_band_does_not_repost(self):
        """Second heartbeat in the same warn band must be silent —
        otherwise each 10-minute poll spams #progress."""
        self._register(
            "agent-a",
            quota_5h_used_pct=0.82,
            quota_5h_reset_at="2026-04-22T01:00:00Z",
        )
        check_agent_quota_pressure("agent-a", post=self._post)
        first_count = len(self.posts)

        # Second heartbeat — re-register + update_heartbeat style, same
        # quota figures. State must survive the re-register.
        self._register(
            "agent-a",
            quota_5h_used_pct=0.84,
            quota_5h_reset_at="2026-04-22T01:00:00Z",
        )
        check_agent_quota_pressure("agent-a", post=self._post)
        self.assertEqual(len(self.posts), first_count)
        self.assertEqual(_agents["agent-a"]["quota_state_5h"], STATE_WARN)

    def test_state_preserved_across_reregister(self):
        """Prev-preserve regression guard — the state slot must survive
        a register_agent call with the quota fields omitted entirely."""
        self._register(
            "agent-a",
            quota_5h_used_pct=0.96,
        )
        check_agent_quota_pressure("agent-a", post=self._post)
        self.assertEqual(
            _agents["agent-a"]["quota_state_5h"], STATE_ESCALATE
        )

        # Re-register without the quota keys (e.g. WS reconnect
        # heartbeat from a path that doesn't carry quota telemetry).
        self._register("agent-a")
        self.assertEqual(
            _agents["agent-a"]["quota_state_5h"], STATE_ESCALATE
        )

    def test_update_heartbeat_triggers_check(self):
        """The heartbeat hot path (update_heartbeat) fires the state
        orochi_machine without the caller having to invoke quota_watch
        explicitly. This is the production wiring — REST handler +
        WS handler both go through update_heartbeat."""
        import hub.quota_watch as quota_watch

        captured: list[tuple[str, str]] = []

        def capture(channel: str, text: str) -> None:
            captured.append((channel, text))

        original_make = quota_watch._make_workspace_post
        quota_watch._make_workspace_post = lambda ws_id: capture
        try:
            self._register(
                "agent-a",
                quota_7d_used_pct=0.97,
                quota_7d_reset_at="2026-04-28T01:00:00Z",
            )
            update_heartbeat("agent-a")
        finally:
            quota_watch._make_workspace_post = original_make

        channels = [c for c, _ in captured]
        self.assertIn("#escalation", channels)
        self.assertIn("#ywatanabe", channels)
        self.assertEqual(
            _agents["agent-a"]["quota_state_7d"], STATE_ESCALATE
        )

    def test_percentage_input_is_normalized(self):
        """Producer-agnostic — 0..100 percentages are rescaled."""
        self._register("agent-a", quota_5h_used_pct=82)
        check_agent_quota_pressure("agent-a", post=self._post)
        self.assertEqual(_agents["agent-a"]["quota_state_5h"], STATE_WARN)

    def test_full_lifecycle_ok_warn_escalate_recover(self):
        """End-to-end sequence a real agent might traverse over a 5h
        window: ok → warn → escalate → ok. Each transition fires once."""
        # ok → warn
        self._register("agent-a", quota_5h_used_pct=0.82)
        check_agent_quota_pressure("agent-a", post=self._post)
        # warn → escalate
        self._register("agent-a", quota_5h_used_pct=0.97)
        check_agent_quota_pressure("agent-a", post=self._post)
        # escalate → ok (reset fired)
        self._register("agent-a", quota_5h_used_pct=0.01)
        check_agent_quota_pressure("agent-a", post=self._post)

        channels = [c for c, _ in self.posts]
        # Exactly: warn #progress, escalate #escalation + #ywatanabe,
        # recovery #progress.
        self.assertEqual(channels.count("#progress"), 2)  # warn + recovery
        self.assertEqual(channels.count("#escalation"), 1)
        self.assertEqual(channels.count("#ywatanabe"), 1)
        self.assertEqual(_agents["agent-a"]["quota_state_5h"], STATE_OK)
