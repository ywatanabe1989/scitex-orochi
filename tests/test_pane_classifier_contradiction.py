"""Tests for the pane-state classifier `stale` path + contradiction logger.

Exercises the 2026-04-21 extension (lead msg#15541): the classifier now
emits `stale` when the pane tail has been byte-identical for
N consecutive push cycles with no busy-animation marker, and the
companion helpers surface a `orochi_classifier_note` + append tmux-tail
evidence to a dedicated log when `orochi_pane_state == "stale"` coincides
with `liveness == "online"` (the "3rd LED stale vs 4th LED green"
contradiction on the dashboard).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# scripts/client isn't a proper package in the repo — add it to path so
# the `_collect_agent_metadata` module is importable under its current layout.
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "client"))

from _collect_agent_metadata import _classifier  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """Redirect the classifier's per-agent state dir + contradictions
    log to a pytest tmp_path so tests never touch the user's real
    ~/.local/state/scitex/ files."""
    state_dir = tmp_path / "classifier-state"
    log_path = tmp_path / "fleet-pane-contradictions.log"
    monkeypatch.setattr(_classifier, "_STATE_DIR", state_dir)
    monkeypatch.setattr(_classifier, "_CONTRADICTIONS_LOG", log_path)
    return state_dir, log_path


# ---------------------------------------------------------------------------
# Pre-existing classifier states still work
# ---------------------------------------------------------------------------


def test_running_marker_beats_everything():
    pane = "some output\nesc to interrupt\n❯ "
    assert (
        _classifier._classify_orochi_pane_state(pane, pane, agent="t-agent-run")
        == "running"
    )


def test_yn_prompt_classified():
    pane = "Continue? [y/N]"
    assert (
        _classifier._classify_orochi_pane_state(pane, pane, agent="t-agent-yn")
        == "y_n_prompt"
    )


def test_empty_pane_returns_empty_string():
    assert _classifier._classify_orochi_pane_state("", "", agent="t-agent-empty") == ""


# ---------------------------------------------------------------------------
# New `stale` path
# ---------------------------------------------------------------------------


def test_single_call_does_not_flip_to_stale():
    pane = "just idle stuff\n$ "
    assert (
        _classifier._classify_orochi_pane_state(pane, pane, agent="t-agent-single")
        == "idle"
    )


def test_stagnation_across_cycles_emits_stale(_isolate_state):
    agent = "t-agent-stale"
    pane = "> some boring prompt with no markers\n"
    # First call seeds the digest (count=0, treated as "changed").
    assert _classifier._classify_orochi_pane_state(pane, pane, agent=agent) == "idle"
    # 2nd call: same digest → count=1.
    assert _classifier._classify_orochi_pane_state(pane, pane, agent=agent) == "idle"
    # 3rd call: count=2.
    assert _classifier._classify_orochi_pane_state(pane, pane, agent=agent) == "idle"
    # 4th call: count=3 → threshold met, flips to stale.
    assert _classifier._classify_orochi_pane_state(pane, pane, agent=agent) == "stale"


def test_busy_animation_suppresses_stale(_isolate_state):
    agent = "t-agent-busy"
    # Pane bytes are identical across cycles but the Mulling animation
    # says the agent is busy — never flip to stale.
    pane = "* Mulling… (12s)\n"
    for _ in range(6):
        assert (
            _classifier._classify_orochi_pane_state(pane, pane, agent=agent) == "idle"
        )


def test_pane_change_resets_stagnation_counter(_isolate_state):
    agent = "t-agent-reset"
    pane_a = "> orochi_version A\n"
    pane_b = "> orochi_version B\n"
    # 4 identical cycles — would flip to stale on the 4th.
    for _ in range(3):
        _classifier._classify_orochi_pane_state(pane_a, pane_a, agent=agent)
    assert (
        _classifier._classify_orochi_pane_state(pane_a, pane_a, agent=agent) == "stale"
    )
    # Pane changes — counter must reset, back to idle.
    assert (
        _classifier._classify_orochi_pane_state(pane_b, pane_b, agent=agent) == "idle"
    )
    # And needs the full threshold again before re-flipping.
    assert (
        _classifier._classify_orochi_pane_state(pane_b, pane_b, agent=agent) == "idle"
    )


def test_stale_respects_empty_agent_kwarg():
    """With no agent id the classifier can't persist state, so it must
    fall back to the legacy stateless `idle` / `""` behavior and never
    emit `stale`."""
    pane = "> boring\n"
    for _ in range(10):
        assert _classifier._classify_orochi_pane_state(pane, pane) == "idle"


# ---------------------------------------------------------------------------
# Contradiction detector
# ---------------------------------------------------------------------------


def test_detect_contradiction_flags_stale_vs_online():
    note = _classifier._detect_contradiction(
        orochi_pane_state="stale", liveness="online"
    )
    assert note == "contradiction:3rd-stale-vs-4th-green"


def test_detect_contradiction_silent_when_liveness_not_green():
    assert (
        _classifier._detect_contradiction(orochi_pane_state="stale", liveness="stale")
        == ""
    )
    assert (
        _classifier._detect_contradiction(
            orochi_pane_state="stale", liveness="offline"
        )
        == ""
    )
    assert (
        _classifier._detect_contradiction(orochi_pane_state="stale", liveness=None)
        == ""
    )


def test_detect_contradiction_silent_for_non_stale_state():
    assert (
        _classifier._detect_contradiction(
            orochi_pane_state="running", liveness="online"
        )
        == ""
    )
    assert (
        _classifier._detect_contradiction(
            orochi_pane_state="idle", liveness="online"
        )
        == ""
    )


# ---------------------------------------------------------------------------
# Evidence log
# ---------------------------------------------------------------------------


def test_log_contradiction_evidence_writes_record(_isolate_state):
    _state_dir, log_path = _isolate_state
    orochi_pane_tail = "line1\nline2\nline3\n"
    written = _classifier._log_contradiction_evidence(
        agent="head-test",
        orochi_pane_state="stale",
        liveness="online",
        tmux_tail=orochi_pane_tail,
    )
    assert written == log_path
    content = log_path.read_text(encoding="utf-8")
    assert "agent=head-test" in content
    assert "note=contradiction:3rd-stale-vs-4th-green" in content
    assert "orochi_pane_state=stale" in content
    assert "liveness=online" in content
    # tail verbatim (last 40 lines — here we only have 3)
    assert "line1" in content and "line2" in content and "line3" in content


def test_log_contradiction_evidence_truncates_tail_to_40_lines(tmp_path):
    log_path = tmp_path / "contradictions.log"
    tail = "\n".join(f"L{i}" for i in range(100))
    _classifier._log_contradiction_evidence(
        agent="head-long",
        orochi_pane_state="stale",
        liveness="online",
        tmux_tail=tail,
        log_path=log_path,
    )
    content = log_path.read_text(encoding="utf-8")
    # L0..L59 must have been dropped (only last 40 kept)
    assert "L59\n" not in content
    # L60..L99 must be present
    assert "L60" in content
    assert "L99" in content


def test_log_contradiction_evidence_appends(tmp_path):
    log_path = tmp_path / "contradictions.log"
    for i in range(3):
        _classifier._log_contradiction_evidence(
            agent=f"agent-{i}",
            orochi_pane_state="stale",
            liveness="online",
            tmux_tail=f"tail-{i}\n",
            log_path=log_path,
        )
    content = log_path.read_text(encoding="utf-8")
    assert content.count("note=contradiction:3rd-stale-vs-4th-green") == 3
    assert "agent=agent-0" in content
    assert "agent=agent-1" in content
    assert "agent=agent-2" in content


# ---------------------------------------------------------------------------
# Expanded busy-marker set (2026-04-21, fix/classifier-busy-markers-expand).
#
# Each test drives the classifier across the full `_STALE_CYCLES_THRESHOLD`+1
# cycles with a byte-identical pane. Without the new markers the classifier
# would flip to `stale` on the last call; with them it must stay `idle`.
# ---------------------------------------------------------------------------


def _assert_never_stale(pane: str, agent: str, cycles: int = 6) -> None:
    """Helper: `pane` held constant for many cycles must not go `stale`."""
    for _ in range(cycles):
        state = _classifier._classify_orochi_pane_state(pane, pane, agent=agent)
        assert state != "stale", (
            f"classifier flipped to stale on pane containing marker; "
            f"pane={pane!r}, agent={agent}"
        )


# --- Group A: present-tense spinner gerunds --------------------------------


@pytest.mark.parametrize(
    "marker",
    [
        "Cogitating",
        "Deliberating",
        "Contemplating",
        "Considering",
        "Analysing",
        "Analyzing",
        "Ruminating",
        "Simmering",
        "Percolating",
        "Noodling",
    ],
)
def test_present_tense_spinner_gerund_suppresses_stale(
    _isolate_state, marker
):
    agent = f"t-agent-gerund-{marker.lower()}"
    pane = f"some boring static output\n* {marker}… (12s)\n"
    _assert_never_stale(pane, agent)


# --- Group B: past-tense "X for Ns" spinner --------------------------------


@pytest.mark.parametrize(
    "marker_line",
    [
        "✻ Baked for 1m 42s",
        "✻ Brewed for 35s",
        "✻ Cogitated for 39s",
        "✻ Cooked for 1m 28s",
        "✻ Thought for 12s",
        "✻ Pondered for 2m 05s",
    ],
)
def test_past_tense_spinner_suppresses_stale(_isolate_state, marker_line):
    """Past-tense '✻ Baked for 40s' etc. — the agent just finished a
    streaming burst and is composing its reply. Pane looks static but
    the session is alive. This was the #1 false-positive class in the
    contradiction log on head-ywata-note-win."""
    agent = f"t-agent-past-{abs(hash(marker_line)) % 1000}"
    pane = f"some tool output here\n{marker_line}\n"
    _assert_never_stale(pane, agent)


# --- Group C: subagent / background markers --------------------------------


def test_local_agent_still_running_suppresses_stale(_isolate_state):
    """'1 local agent still running' footer means the main session
    dispatched a subagent and is awaiting results — very much alive."""
    agent = "t-agent-subagent"
    pane = (
        "  Called scitex-orochi (ctrl+o to expand)\n"
        "✻ Brewed for 35s · 1 local agent still running\n"
    )
    _assert_never_stale(pane, agent)


def test_local_agents_plural_suppresses_stale(_isolate_state):
    agent = "t-agent-orochi_subagents-plural"
    pane = "✻ Cooked for 1m 28s · 3 local agents still running\n"
    _assert_never_stale(pane, agent)


def test_backgrounded_agent_suppresses_stale(_isolate_state):
    agent = "t-agent-bg"
    pane = (
        "● Agent(Pane-state classifier contradiction detection)\n"
        "  ⎿  Backgrounded agent (↓ to manage · ctrl+o to expand)\n"
    )
    _assert_never_stale(pane, agent)


# --- Group D: TodoWrite task-list static view ------------------------------


@pytest.mark.parametrize(
    "header",
    [
        "1 tasks (0 done, 1 in progress, 0 open)",
        "2 tasks (1 done, 1 in progress, 0 open)",
        "5 tasks (2 done, 2 in progress, 1 open)",
        "1 task (0 done, 1 in progress)",
    ],
)
def test_todowrite_task_list_header_suppresses_stale(_isolate_state, header):
    """Classic false-positive from the contradiction log: the TodoWrite
    rendering is byte-identical across cycles but the agent is deep in
    a deliberation turn."""
    agent = f"t-agent-todo-{abs(hash(header)) % 1000}"
    pane = (
        f"  {header}\n"
        "  ◼ pane-state classifier: 3rd-stale vs 4th-green contradiction dete…\n"
    )
    _assert_never_stale(pane, agent)


def test_todowrite_bullet_alone_suppresses_stale(_isolate_state):
    """Even without the numeric header, the '◼ ' checkbox glyph is
    distinctive enough (no non-TodoWrite context uses it in CC)."""
    agent = "t-agent-bullet"
    pane = "  ◼ some active task description here\n"
    _assert_never_stale(pane, agent)


# --- Group E: regex patterns -----------------------------------------------


def test_busy_animation_regexes_have_rationales():
    """Each regex entry must carry a non-empty human-readable rationale
    string — the whole point of the refactor was to move away from
    opaque marker lists."""
    assert len(_classifier._BUSY_ANIMATION_REGEXES) > 0
    for pattern, rationale in _classifier._BUSY_ANIMATION_REGEXES:
        assert pattern.pattern, "empty regex"
        assert rationale and len(rationale) > 10, (
            f"rationale too short for {pattern.pattern!r}"
        )


def test_has_busy_animation_matches_all_new_groups():
    """Unit-level coverage of _has_busy_animation across the four new
    groups. Guards against regressions where the consolidated
    _BUSY_ANIMATION_MARKERS tuple loses an entry in a future refactor."""
    samples = [
        "* Deliberating… (18s)",  # group A
        "✻ Cogitated for 39s",  # group B
        "✻ Brewed for 35s · 1 local agent still running",  # groups B+C
        "  ⎿  Backgrounded agent (↓ to manage · ctrl+o to expand)",  # group C
        "  2 tasks (1 done, 1 in progress, 0 open)",  # group D regex
        "  ◼ some in-progress work item",  # group D literal
        "Press up to edit queued messages",  # existing Crunched-like
    ]
    for sample in samples:
        assert _classifier._has_busy_animation(sample), (
            f"_has_busy_animation returned False for {sample!r}"
        )


def test_has_busy_animation_rejects_plain_static_text():
    """Negative control: a genuinely static idle pane must NOT trigger
    any of the new markers."""
    plain = "$ ls\nfoo.py  bar.py  baz.py\n$ "
    assert not _classifier._has_busy_animation(plain)


def test_stale_still_fires_without_busy_markers(_isolate_state):
    """End-to-end regression: after the expansion, a pane with zero
    busy markers must still flip to `stale` on the 4th identical cycle.
    Guards against accidentally matching every pane via an over-broad
    regex."""
    agent = "t-agent-still-stale"
    pane = "just a shell prompt\n$ \n"
    for _ in range(3):
        assert (
            _classifier._classify_orochi_pane_state(pane, pane, agent=agent) == "idle"
        )
    assert (
        _classifier._classify_orochi_pane_state(pane, pane, agent=agent) == "stale"
    )
