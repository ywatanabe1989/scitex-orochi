"""Tests for the worker-progress digest coalescer (todo#272).

Covers:
  - 60 s window → single emit
  - Zero events in a window → ``flush`` returns ``None`` (no heartbeat)
  - Identical signatures coalesce into ``Nx <summary>``
  - ``@worker-progress`` mention triggers MentionPolicy bypass
  - DM path is treated as a mention regardless of text

No WebSocket I/O: the coalescer is pure and takes an injected clock so
the test harness never sleeps.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

# The daemon lives under scripts/server/ (a sibling of the Django app
# tree), so we have to surface that path before importing. Keeping the
# path fiddle inside the test module is fine; hub.tests is never
# imported by the production daemon.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_SERVER = _REPO_ROOT / "scripts" / "server"
if str(_SCRIPTS_SERVER) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_SERVER))

from worker_progress_pkg._digest import (  # noqa: E402
    DEFAULT_WINDOW_S,
    DigestCoalescer,
    InboundEvent,
    MentionPolicy,
)


class FakeClock:
    """Deterministic monotonic clock for the coalescer tests."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _ev(channel="#progress", sender="github", text="CI started", **kw):
    return InboundEvent(
        channel=channel,
        sender=sender,
        text=text,
        ts=0.0,
        is_dm=kw.get("is_dm", False),
        mentions_self=kw.get("mentions_self", False),
    )


class DigestCoalescerTest(TestCase):
    def test_empty_window_flushes_none(self):
        clock = FakeClock()
        c = DigestCoalescer(now=clock)
        # Advance past the window with zero events.
        clock.advance(DEFAULT_WINDOW_S + 1)
        self.assertIsNone(c.flush())

    def test_single_event_emits_one_line_per_window(self):
        clock = FakeClock()
        c = DigestCoalescer(now=clock)
        c.push(_ev(text="CI started: foo/bar #1"))
        # Not yet time to flush.
        self.assertIsNone(c.flush())
        clock.advance(DEFAULT_WINDOW_S + 1)
        line = c.flush()
        self.assertIsNotNone(line)
        self.assertIn("[progress ", line)
        self.assertIn("1 events", line)
        self.assertIn("#progress", line)
        # Next window starts empty.
        self.assertIsNone(c.flush())

    def test_identical_signatures_coalesce(self):
        clock = FakeClock()
        c = DigestCoalescer(now=clock)
        # 40 "CI started" posts from the same sender/channel — same sig.
        for _ in range(40):
            c.push(_ev(text="CI started"))
        clock.advance(DEFAULT_WINDOW_S + 0.1)
        line = c.flush()
        self.assertIsNotNone(line)
        self.assertIn("40x", line)
        self.assertIn("40 events", line)

    def test_multiple_signatures_top_n_highlights(self):
        clock = FakeClock()
        c = DigestCoalescer(now=clock)
        # Three distinct signatures with differing counts.
        for _ in range(5):
            c.push(_ev(text="A started"))
        for _ in range(3):
            c.push(_ev(text="B started"))
        for _ in range(1):
            c.push(_ev(text="C started"))
        # A 4th, lower-ranked signature should roll into "+more".
        c.push(_ev(text="D started"))
        clock.advance(DEFAULT_WINDOW_S + 0.1)
        line = c.flush()
        self.assertIsNotNone(line)
        self.assertIn("10 events", line)
        # Top 3 visible by count.
        self.assertIn("5x", line)
        self.assertIn("3x", line)
        self.assertIn("+1 more", line)

    def test_line_cap_under_200_chars(self):
        clock = FakeClock()
        c = DigestCoalescer(now=clock)
        for i in range(30):
            # 30 distinct long signatures.
            c.push(_ev(text=f"long event number {i:02d} with detail"))
        clock.advance(DEFAULT_WINDOW_S + 0.1)
        line = c.flush()
        self.assertIsNotNone(line)
        self.assertLessEqual(len(line), 200)


class MentionPolicyTest(TestCase):
    def test_at_mention_triggers_bypass(self):
        ev = _ev(text="hey @worker-progress ping")
        self.assertTrue(MentionPolicy.is_mention(ev))

    def test_at_agent_prefix_form(self):
        ev = _ev(text="FYI @agent-worker-progress")
        self.assertTrue(MentionPolicy.is_mention(ev))

    def test_no_mention_plain_text(self):
        ev = _ev(text="unrelated update in #progress")
        self.assertFalse(MentionPolicy.is_mention(ev))

    def test_dm_is_always_mention(self):
        ev = _ev(
            channel="dm:ywatanabe|worker-progress",
            sender="ywatanabe",
            text="anything",
            is_dm=True,
        )
        self.assertTrue(MentionPolicy.is_mention(ev))

    def test_ack_line_renders_shortly(self):
        ev = _ev(text="@worker-progress hi")
        line = MentionPolicy.ack_line(ev)
        self.assertIn("todo#272", line)
        self.assertLessEqual(len(line), 200)

    def test_ack_line_dm_path(self):
        ev = _ev(
            channel="dm:ywatanabe|worker-progress",
            sender="ywatanabe",
            text="hello",
            is_dm=True,
        )
        line = MentionPolicy.ack_line(ev)
        self.assertIn("received", line)
        self.assertIn("todo#272", line)
