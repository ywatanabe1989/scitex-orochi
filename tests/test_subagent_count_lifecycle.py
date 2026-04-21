"""End-to-end lifecycle tests for ``parse_subagent_count``.

Both Layer 1 (server-side auto-dispatch) and Layer 2 (hungry-signal DM,
PR #329) depend on ``subagent_count == 0`` detection being accurate. If
the count fails to decrement when subagents finish, auto-dispatch fires
when the head is actually busy (false negative) or misfires when it
shouldn't (false positive). This module pins the parser's behaviour
across every transition the tmux pane can emit during a real subagent
batch — spawn, ramp-up, partial completion, full completion, and the
"marker disappears" quiet state — plus regression guards for
false-positive chat text and multi-marker panes.

The parser under test lives at
``scripts/client/agent_meta_pkg/_pane.py::parse_subagent_count``.
A mirror implementation lives in ``scitex-agent-container`` (separate
repo); that one needs its own test suite there — see PR body for
follow-up.

Scope: lifecycle parser behaviour only. The hub-side round-trip (how
``subagent_count`` travels through the heartbeat frame to the registry)
is covered by ``hub/tests/consumers/test_subagent_count_roundtrip.py``.
The hungry-signal counter / auto-dispatch streak logic is covered by
``tests/test_hungry_signal_counter.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# agent_meta_pkg isn't installed into site-packages — make it importable.
_AGENT_META_DIR = Path(__file__).resolve().parents[1] / "scripts" / "client"
if str(_AGENT_META_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_META_DIR))

from agent_meta_pkg._pane import parse_subagent_count  # noqa: E402

# ---------------------------------------------------------------------------
# Happy-path parametric coverage — every count / grammar variant the
# Claude Code status line is known to emit.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pane_text, expected",
    [
        # Singular form (1 agent, present participle)
        ("1 local agent running", 1),
        # Plural, small count
        ("2 local agents running", 2),
        ("3 local agents running", 3),
        # Plural, larger count (stress the \d+ group)
        ("5 local agents running", 5),
        # "still running" variant — emitted once the batch has been
        # alive long enough to tick the status-line refresh.
        ("1 local agent still running", 1),
        ("2 local agents still running", 2),
        # Full status-line shape — leading glyph, trailing elapsed time
        ("  ✶ 1 local agent running · 2s\n❯ ", 1),
        ("  ✢ 5 local agents still running · 45s\n", 5),
        # Zero — Claude Code briefly emits "0 local agents" while the
        # batch drains. Parser must treat this as 0, not as "no marker".
        ("0 local agents", 0),
        ("0 local agents running", 0),
    ],
    ids=[
        "singular-1",
        "plural-2",
        "plural-3",
        "plural-5",
        "singular-still",
        "plural-still",
        "full-status-line-1",
        "full-status-line-5-still",
        "zero-no-running-suffix",
        "zero-with-running",
    ],
)
def test_count_parsed_from_marker(pane_text: str, expected: int) -> None:
    """The regex extracts the advertised integer across every known variant."""
    assert parse_subagent_count(pane_text) == expected


# ---------------------------------------------------------------------------
# Zero state — marker absent / pane empty. Both must parse to 0 so the
# heartbeat carries an authoritative 0 rather than a stale prior count.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pane_text",
    [
        "",  # empty pane (WS just connected, no scrollback yet)
        "agent session active",  # no marker, normal chat output
        "regular chat output\nnothing special here\n❯ ",  # idle prompt
        "doing some work\n  ⎿ tool finished\n❯ ",  # finished-tool idle state
        "0 local agents\n",  # explicit zero — covered by parametric above,
        # but pinned here because "marker disappears" and "zero marker" are
        # two distinct real-world transitions and both must floor at 0.
    ],
    ids=[
        "empty-pane",
        "no-marker-phrase",
        "idle-prompt",
        "finished-tool",
        "zero-marker",
    ],
)
def test_zero_state_parses_to_zero(pane_text: str) -> None:
    """Empty / marker-less / explicit-zero panes all report 0."""
    assert parse_subagent_count(pane_text) == 0


def test_none_pane_returns_zero() -> None:
    """A None pane (tmux capture failed) must not raise — treat as 0."""
    # The production signature takes str, but defensive call-sites pass
    # through whatever ``capture_pane`` returned. Pin the None-safe path.
    assert parse_subagent_count(None) == 0  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Full spawn → run → complete lifecycle. Two distinct parses against the
# same captured pane must yield the transition the hub expects.
# ---------------------------------------------------------------------------


def test_spawn_then_completion_transition() -> None:
    """Burst transition: 1 running, later 0 running.

    The head's heartbeat loop captures the pane twice across two ticks.
    Tick 1 captures the pane while an Agent call is in flight → parser
    returns 1. Tick 2 captures after the Agent returned and the status
    line cleared → parser returns 0. Both parses must be independent
    and correct so the hub's ``subagent_count`` field tracks reality.
    """
    pane_tick_1 = "  ✶ 1 local agent running · 2s\n❯ "
    pane_tick_2 = "  ⎿ Agent finished\n❯ "  # marker fully gone
    assert parse_subagent_count(pane_tick_1) == 1
    assert parse_subagent_count(pane_tick_2) == 0


def test_partial_completion_transition() -> None:
    """3 spawned, 1 finishes → pane shows "2 local agents running"."""
    pane_tick_1 = "  ✶ 3 local agents running · 5s\n❯ "
    pane_tick_2 = "  ✢ 2 local agents still running · 12s\n❯ "
    pane_tick_3 = "  ⎿ Agent finished\n❯ "
    assert parse_subagent_count(pane_tick_1) == 3
    assert parse_subagent_count(pane_tick_2) == 2
    assert parse_subagent_count(pane_tick_3) == 0


def test_ramp_up_transition() -> None:
    """Parser tracks monotonic spawn-up: 1 → 2 → 5."""
    # Head spawns Agents one at a time across three ticks.
    assert parse_subagent_count("  ✶ 1 local agent running · 1s\n❯ ") == 1
    assert parse_subagent_count("  ✶ 2 local agents running · 2s\n❯ ") == 2
    assert parse_subagent_count("  ✶ 5 local agents running · 3s\n❯ ") == 5


def test_zero_to_one_to_zero_roundtrip() -> None:
    """Cold-start → one Agent spawn → completion back to idle."""
    assert parse_subagent_count("") == 0  # cold start
    assert parse_subagent_count("1 local agent running") == 1  # spawn
    assert parse_subagent_count("0 local agents") == 0  # wind-down
    assert parse_subagent_count("❯ ") == 0  # marker fully gone


# ---------------------------------------------------------------------------
# False-positive regression guards. The current regex anchors on the
# literal ``running`` trailer precisely to stop these from matching; pin
# that so a future refactor that broadens the regex breaks loudly.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pane_text",
    [
        # Chat prose mentioning the count-like phrase — the "running"
        # trailer guards against this. Listed in msg#16389 as the
        # canonical regression-guard case.
        "reviewing 2 local agent names that were stale last cycle",
        "2 local agent names are stale",
        # Another false-positive shape — possessive construction
        "the 4 local agent instances each report their own state",
        # Error message citing count without the trailer
        "error: expected 1 local agent; got 3",
    ],
    ids=[
        "chat-names-are-stale",
        "chat-names-are-stale-short",
        "possessive-instances",
        "error-citing-count",
    ],
)
def test_false_positive_regression_guards(pane_text: str) -> None:
    """Chat / doc / error text mentioning "local agent" without the
    ``running`` trailer must NOT match.

    The old substring regex (``(\\d+) local agent``) fired on all of
    these and inflated ``subagent_count``. The current regex requires
    the ``running`` trailer; pin that so the guard doesn't regress.
    """
    assert parse_subagent_count(pane_text) == 0


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known false-positive: quoted docs / chat prose containing the "
        "literal string \"N local agents running\" — e.g. a help-text "
        "citation or a channel message quoting the marker phrase — are "
        "matched by the current regex even though the surrounding "
        "context makes clear they are not live status lines. A future "
        "fix could anchor the regex to start-of-line (``^``) or require "
        "leading whitespace + a status-line glyph (``✶`` / ``✢``). "
        "Tracked as a follow-up; this test pins the current buggy "
        "behaviour so the fix is visible when it lands."
    ),
)
def test_quoted_marker_phrase_false_positive() -> None:
    """Documented bug: quoted docs containing the marker phrase match.

    When a chat message or help-text quotes the literal status-line
    phrase (e.g. ``see docs: '3 local agents running' appears when...``)
    the regex matches and the parser reports 3 even though no subagent
    is actually running. This is a known false positive — filing a
    follow-up issue keeps scope out of the lifecycle-test PR.
    """
    # Expected (correct) behaviour: quoted citation should not count.
    pane = "see docs: '3 local agents running' appears when a batch is active"
    assert parse_subagent_count(pane) == 0


# ---------------------------------------------------------------------------
# Prefix / suffix tolerance — real tmux panes are full of control codes,
# box-drawing characters, and trailing whitespace. The marker must still
# be found.
# ---------------------------------------------------------------------------


def test_leading_whitespace_tolerated() -> None:
    """Leading spaces + glyphs don't block the match."""
    assert parse_subagent_count("     1 local agent running") == 1
    assert parse_subagent_count("\t\t3 local agents running") == 3


def test_trailing_whitespace_tolerated() -> None:
    """Trailing padding / elapsed-time suffix doesn't block the match."""
    assert parse_subagent_count("1 local agent running · 2s") == 1
    assert parse_subagent_count("1 local agent running   \n") == 1
    assert parse_subagent_count("1 local agent running\r\n") == 1


def test_newlines_and_multiline_pane() -> None:
    """Marker embedded in a multi-line capture still resolves."""
    pane = "\n".join([
        "some earlier output",
        "  ⎿ tool output",
        "  ✶ 4 local agents running · 7s",
        "❯ ",
    ])
    assert parse_subagent_count(pane) == 4


def test_color_escape_codes_do_not_break_match() -> None:
    """ANSI escape sequences around the marker don't consume the digit.

    tmux capture-pane defaults to stripping escapes, but some call
    sites pass raw text through; pin the tolerance so we don't
    silently lose a match when the pipeline changes.
    """
    # The regex doesn't anchor to start-of-line, and the digit+literal
    # "local agents running" is the matched run, so ESC sequences on
    # either side are ignored.
    pane = "\x1b[32m  ✶ 2 local agents running · 3s\x1b[0m\n"
    assert parse_subagent_count(pane) == 2


def test_case_insensitive_markers() -> None:
    """Future-proofing: the regex is case-insensitive per the current
    implementation. Pin that so a refactor doesn't drop ``re.IGNORECASE``
    silently — there's no cost to keeping the match forgiving and the
    hungry-signal / auto-dispatch path wants the broadest match possible.
    """
    assert parse_subagent_count("1 Local Agent Running") == 1
    assert parse_subagent_count("2 LOCAL AGENTS RUNNING") == 2
    assert parse_subagent_count("3 LOCAL AGENTS STILL RUNNING") == 3


# ---------------------------------------------------------------------------
# Multi-marker pane — pin first-match semantics so a future refactor
# that changes to "last match" breaks explicitly rather than silently.
# ---------------------------------------------------------------------------


def test_multi_marker_returns_first_match() -> None:
    """Pane scrollback can contain a stale earlier marker above a newer
    one (pane is 500 lines of history, the batch transition is shorter
    than that). Current implementation uses ``re.search``, which returns
    the first (top-most) match. Pin the behaviour; if a future author
    wants last-match / latest-wins semantics they should change this
    test in the same commit so the change is explicit.
    """
    pane = (
        "  ✶ 2 local agents running\n"
        "... later ticks ...\n"
        "  ✢ 4 local agents still running\n"
    )
    assert parse_subagent_count(pane) == 2


def test_multi_marker_stale_above_current() -> None:
    """Realistic shape: an old fully-completed batch left
    "0 local agents running" behind, then a new batch spawned. First
    match wins — hub sees 0 until the old line scrolls off, at which
    point the new count takes over. The test pins the order-sensitive
    behaviour; whether "stale wins" is actually desirable is a separate
    concern (see PR body for follow-up notes).

    Note: only a stale "0 local agents **running**" line steals the
    match — a bare "0 local agents" has no ``running`` trailer, so the
    regex skips past it to the live ``N local agents running`` line
    below. Both shapes are exercised here.
    """
    # Shape A: stale line still has the ``running`` trailer → first-match
    # semantics mean the stale 0 wins.
    pane_stale_with_running = (
        "  ⎿ 0 local agents running\n"
        "...\n"
        "  ✶ 3 local agents running · 2s\n"
    )
    assert parse_subagent_count(pane_stale_with_running) == 0

    # Shape B: stale line dropped the ``running`` trailer → the stale
    # line fails to match and the live count wins.
    pane_stale_without_running = (
        "  ⎿ 0 local agents\n"
        "...\n"
        "  ✶ 3 local agents running · 2s\n"
    )
    assert parse_subagent_count(pane_stale_without_running) == 3


# ---------------------------------------------------------------------------
# Race conditions. Heartbeat may sample the pane mid-transition (the
# status line is being redrawn). The parser is expected to return
# whatever the pane says *right now*; the hub is eventually consistent
# via the next heartbeat.
# ---------------------------------------------------------------------------


def test_heartbeat_during_stale_frame_records_stale_count() -> None:
    """Race: pane still shows "2 local agents running" while both have
    actually just finished. The parser returns 2 — that's correct
    behaviour — and the hub records 2 until the next heartbeat. The
    contract is eventual-consistency, not mid-tick correctness.
    """
    # A realistic stale frame: the status-line redraw hasn't happened
    # yet even though the Agent calls returned.
    stale_pane = "  ✢ 2 local agents running · 8s\n  ⎿ Done\n❯ "
    assert parse_subagent_count(stale_pane) == 2

    # Next heartbeat samples the post-redraw pane → hub updates.
    post_redraw = "  ⎿ Done\n❯ "
    assert parse_subagent_count(post_redraw) == 0


def test_count_never_goes_negative() -> None:
    """Defensive: even if a pathological pane somehow contained a
    negative sign before the digit, the regex's ``\\d+`` group can't
    capture the sign — so the count stays non-negative. The hub's
    ``set_subagent_count`` floors at zero as a second line of defence,
    but we want the parser to do the right thing on its own too.
    """
    # ``-3 local agents running`` — the regex matches "3 local agents
    # running" (the minus sign is not consumed by ``\\d+``), so the
    # count is 3 not -3.
    assert parse_subagent_count("-3 local agents running") == 3
    assert parse_subagent_count("-1 local agent running") == 1
    # The produced value is always a non-negative int.
    assert parse_subagent_count("-99 local agents running") >= 0
