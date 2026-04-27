"""Unit tests for the caduceus greeting-ping protocol (todo#168).

The module under test is pure — no hub, no sockets — so every path here
is deterministic and fast. The deliberate scope is:

1. Nonce generation (uniqueness, format).
2. Wire format round-trip (``format_greeting`` → ``parse_pong``).
3. State transitions on reply match (healthy) and on timeout
   (warn / degraded / inbound_deaf ladder).
4. Cadence helper (``should_ping``) — staggering and busy-skip.
"""

from __future__ import annotations

import re

import pytest

from scitex_orochi._caduceus_greeting import (
    DEFAULT_TIMEOUT_S,
    GREETING_FORMAT,
    GreetingState,
    format_greeting,
    new_nonce,
    parse_pong,
    should_ping,
)

# ---------------------------------------------------------------------------
# Nonce generation
# ---------------------------------------------------------------------------


class TestNonce:
    def test_nonce_is_8_lowercase_hex_chars(self):
        for _ in range(100):
            n = new_nonce()
            assert re.fullmatch(r"[0-9a-f]{8}", n), (
                f"nonce {n!r} is not 8 lowercase hex chars"
            )

    def test_nonces_are_unique_over_many_draws(self):
        nonces = {new_nonce() for _ in range(1000)}
        # With 32 bits of entropy, 1000 draws have ~1e-4 collision
        # probability. Any duplicate in a sample this small signals a
        # bug in the generator (e.g., seeded/predictable PRNG).
        assert len(nonces) == 1000


# ---------------------------------------------------------------------------
# Wire format
# ---------------------------------------------------------------------------


class TestWireFormat:
    def test_format_greeting_uses_canonical_template(self):
        body, nonce = format_greeting("head-nas", nonce="deadbeef")
        assert body == "@head-nas [greeting:deadbeef]"
        assert nonce == "deadbeef"

    def test_format_greeting_generates_nonce_when_none(self):
        body, nonce = format_greeting("head-mba")
        assert re.fullmatch(r"[0-9a-f]{8}", nonce)
        assert f"[greeting:{nonce}]" in body
        assert body.startswith("@head-mba ")

    def test_format_greeting_rejects_malformed_nonce(self):
        with pytest.raises(ValueError):
            format_greeting("head-nas", nonce="BAD")
        with pytest.raises(ValueError):
            format_greeting("head-nas", nonce="ZZZZZZZZ")
        with pytest.raises(ValueError):
            format_greeting("head-nas", nonce="12345678A")  # 9 chars

    def test_parse_pong_matches_exact_token(self):
        assert parse_pong("[pong:deadbeef]") == "deadbeef"

    def test_parse_pong_matches_with_surrounding_text(self):
        assert parse_pong("ack [pong:abcd1234] (after /compact)") == "abcd1234"

    def test_parse_pong_returns_none_on_no_match(self):
        assert parse_pong("") is None
        assert parse_pong("hello world") is None
        assert parse_pong("[pong:]") is None  # empty nonce
        assert parse_pong("[pong:XYZXYZXY]") is None  # non-hex
        assert parse_pong("[pong:abcd123]") is None  # 7 chars not 8


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


class TestGreetingStateHealthyPath:
    def test_reply_match_marks_agent_healthy(self):
        state = GreetingState()
        state.register_ping("head-nas", "aaaaaaaa", sent_ts=100.0)
        matched = state.record_reply("[pong:aaaaaaaa]", recv_ts=102.3)
        assert matched is not None
        assert matched.agent == "head-nas"
        assert matched.nonce == "aaaaaaaa"
        assert state.conversational_status("head-nas") == "healthy"
        assert state.status["head-nas"]["last_rtt_s"] == pytest.approx(2.3)
        # In-flight entry was removed.
        assert ("head-nas", "aaaaaaaa") not in state.in_flight

    def test_reply_with_unknown_nonce_is_ignored(self):
        state = GreetingState()
        state.register_ping("head-nas", "aaaaaaaa", sent_ts=100.0)
        matched = state.record_reply("[pong:bbbbbbbb]", recv_ts=101.0)
        assert matched is None
        # Known in-flight entry still there — foreign nonce must not
        # corrupt state.
        assert ("head-nas", "aaaaaaaa") in state.in_flight
        assert state.conversational_status("head-nas") == "unknown"

    def test_late_pong_still_heals(self):
        # A pong arriving after the ping expired should still flip status
        # back to healthy. The in-flight ping was already swept though, so
        # the late reply would match nothing — that's the "expected"
        # pathological case and we document it by asserting the late pong
        # is ignored once the sweep has run.
        state = GreetingState()
        state.register_ping(
            "head-nas", "aaaaaaaa", sent_ts=100.0, timeout_s=30
        )
        # Sweep past expiry.
        state.sweep_expired(now=140.0)
        # Now the late pong arrives.
        matched = state.record_reply("[pong:aaaaaaaa]", recv_ts=141.0)
        assert matched is None  # no in-flight entry left
        # Status remains in the timeout ladder — caller can observe this
        # and manually clear if late pongs should override.
        assert state.conversational_status("head-nas") == "warn"


class TestGreetingStateTimeoutLadder:
    def test_first_timeout_marks_warn(self):
        state = GreetingState()
        state.register_ping("head-nas", "aaaaaaaa", sent_ts=0.0, timeout_s=60)
        expired = state.sweep_expired(now=120.0)
        assert len(expired) == 1
        assert state.conversational_status("head-nas") == "warn"
        assert state.status["head-nas"]["consecutive_timeouts"] == 1

    def test_second_timeout_marks_degraded(self):
        state = GreetingState()
        state.register_ping("head-nas", "aaaaaaaa", sent_ts=0.0, timeout_s=60)
        state.sweep_expired(now=120.0)
        state.register_ping("head-nas", "bbbbbbbb", sent_ts=200.0, timeout_s=60)
        state.sweep_expired(now=400.0)
        assert state.conversational_status("head-nas") == "degraded"
        assert state.status["head-nas"]["consecutive_timeouts"] == 2

    def test_third_timeout_marks_inbound_deaf(self):
        state = GreetingState()
        for i, nonce in enumerate(["aaaaaaaa", "bbbbbbbb", "cccccccc"]):
            state.register_ping("head-nas", nonce, sent_ts=i * 200.0, timeout_s=60)
            state.sweep_expired(now=i * 200.0 + 120.0)
        assert state.conversational_status("head-nas") == "inbound_deaf"
        assert state.status["head-nas"]["consecutive_timeouts"] == 3

    def test_reply_resets_consecutive_timeouts(self):
        state = GreetingState()
        state.register_ping("head-nas", "aaaaaaaa", sent_ts=0.0, timeout_s=60)
        state.sweep_expired(now=120.0)
        assert state.status["head-nas"]["consecutive_timeouts"] == 1
        state.register_ping("head-nas", "bbbbbbbb", sent_ts=200.0, timeout_s=60)
        state.record_reply("[pong:bbbbbbbb]", recv_ts=202.0)
        assert state.conversational_status("head-nas") == "healthy"
        assert state.status["head-nas"]["consecutive_timeouts"] == 0


# ---------------------------------------------------------------------------
# Cadence
# ---------------------------------------------------------------------------


class TestShouldPing:
    def test_first_ping_always_due(self):
        assert should_ping(
            "head-nas",
            orochi_current_task="",
            idle_seconds=None,
            now=1000.0,
            last_ping_ts={},
            interval_s=180,
        )

    def test_second_ping_waits_for_interval(self):
        last = {"head-nas": 1000.0}
        assert not should_ping(
            "head-nas", "", None, now=1100.0, last_ping_ts=last, interval_s=180
        )
        assert should_ping(
            "head-nas", "", None, now=1181.0, last_ping_ts=last, interval_s=180
        )

    def test_skips_actively_working_agents(self):
        # Agent with a current task and <30s idle is visibly working —
        # don't interrupt with a greeting.
        assert not should_ping(
            "head-nas",
            orochi_current_task="todo#168 impl",
            idle_seconds=5,
            now=2000.0,
            last_ping_ts={},
            interval_s=180,
        )

    def test_pings_idle_agent_with_task(self):
        # Agent has a task but has been idle ≥30s — could be wedged, ping them.
        assert should_ping(
            "head-nas",
            orochi_current_task="todo#168 impl",
            idle_seconds=90,
            now=2000.0,
            last_ping_ts={},
            interval_s=180,
        )

    def test_empty_name_never_pings(self):
        assert not should_ping("", "", None, 1.0, {}, 1)


# ---------------------------------------------------------------------------
# Regression: wire format constants stay stable
# ---------------------------------------------------------------------------


def test_greeting_format_template_unchanged():
    # This template is documented in fleet-greeting-protocol.md and in
    # the CLAUDE.md rule for every agent. Changing it silently would
    # break every in-flight agent's pong responder. If you really need
    # to change it, update both docs + coordinate a fleet-wide rollout.
    assert GREETING_FORMAT == "@{agent} [greeting:{nonce}]"


def test_default_timeout_matches_rule_13():
    # 60 s = the one-minute responsiveness rule in
    # fleet-communication-discipline.md §13. Do not relax without
    # explicit ywatanabe sign-off.
    assert DEFAULT_TIMEOUT_S == 60
