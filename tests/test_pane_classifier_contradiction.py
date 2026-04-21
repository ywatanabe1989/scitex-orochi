"""Tests for the pane-state classifier `stale` path + contradiction logger.

Exercises the 2026-04-21 extension (lead msg#15541): the classifier now
emits `stale` when the pane tail has been byte-identical for
N consecutive push cycles with no busy-animation marker, and the
companion helpers surface a `classifier_note` + append tmux-tail
evidence to a dedicated log when `pane_state == "stale"` coincides
with `liveness == "online"` (the "3rd LED stale vs 4th LED green"
contradiction on the dashboard).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# scripts/client isn't a proper package in the repo — add it to path so
# the `agent_meta_pkg` module is importable under its current layout.
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "client"))

from agent_meta_pkg import _classifier  # noqa: E402


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
        _classifier._classify_pane_state(pane, pane, agent="t-agent-run")
        == "running"
    )


def test_yn_prompt_classified():
    pane = "Continue? [y/N]"
    assert (
        _classifier._classify_pane_state(pane, pane, agent="t-agent-yn")
        == "y_n_prompt"
    )


def test_empty_pane_returns_empty_string():
    assert _classifier._classify_pane_state("", "", agent="t-agent-empty") == ""


# ---------------------------------------------------------------------------
# New `stale` path
# ---------------------------------------------------------------------------


def test_single_call_does_not_flip_to_stale():
    pane = "just idle stuff\n$ "
    assert (
        _classifier._classify_pane_state(pane, pane, agent="t-agent-single")
        == "idle"
    )


def test_stagnation_across_cycles_emits_stale(_isolate_state):
    agent = "t-agent-stale"
    pane = "> some boring prompt with no markers\n"
    # First call seeds the digest (count=0, treated as "changed").
    assert _classifier._classify_pane_state(pane, pane, agent=agent) == "idle"
    # 2nd call: same digest → count=1.
    assert _classifier._classify_pane_state(pane, pane, agent=agent) == "idle"
    # 3rd call: count=2.
    assert _classifier._classify_pane_state(pane, pane, agent=agent) == "idle"
    # 4th call: count=3 → threshold met, flips to stale.
    assert _classifier._classify_pane_state(pane, pane, agent=agent) == "stale"


def test_busy_animation_suppresses_stale(_isolate_state):
    agent = "t-agent-busy"
    # Pane bytes are identical across cycles but the Mulling animation
    # says the agent is busy — never flip to stale.
    pane = "* Mulling… (12s)\n"
    for _ in range(6):
        assert (
            _classifier._classify_pane_state(pane, pane, agent=agent) == "idle"
        )


def test_pane_change_resets_stagnation_counter(_isolate_state):
    agent = "t-agent-reset"
    pane_a = "> version A\n"
    pane_b = "> version B\n"
    # 4 identical cycles — would flip to stale on the 4th.
    for _ in range(3):
        _classifier._classify_pane_state(pane_a, pane_a, agent=agent)
    assert (
        _classifier._classify_pane_state(pane_a, pane_a, agent=agent) == "stale"
    )
    # Pane changes — counter must reset, back to idle.
    assert (
        _classifier._classify_pane_state(pane_b, pane_b, agent=agent) == "idle"
    )
    # And needs the full threshold again before re-flipping.
    assert (
        _classifier._classify_pane_state(pane_b, pane_b, agent=agent) == "idle"
    )


def test_stale_respects_empty_agent_kwarg():
    """With no agent id the classifier can't persist state, so it must
    fall back to the legacy stateless `idle` / `""` behavior and never
    emit `stale`."""
    pane = "> boring\n"
    for _ in range(10):
        assert _classifier._classify_pane_state(pane, pane) == "idle"


# ---------------------------------------------------------------------------
# Contradiction detector
# ---------------------------------------------------------------------------


def test_detect_contradiction_flags_stale_vs_online():
    note = _classifier._detect_contradiction(
        pane_state="stale", liveness="online"
    )
    assert note == "contradiction:3rd-stale-vs-4th-green"


def test_detect_contradiction_silent_when_liveness_not_green():
    assert (
        _classifier._detect_contradiction(pane_state="stale", liveness="stale")
        == ""
    )
    assert (
        _classifier._detect_contradiction(
            pane_state="stale", liveness="offline"
        )
        == ""
    )
    assert (
        _classifier._detect_contradiction(pane_state="stale", liveness=None)
        == ""
    )


def test_detect_contradiction_silent_for_non_stale_state():
    assert (
        _classifier._detect_contradiction(
            pane_state="running", liveness="online"
        )
        == ""
    )
    assert (
        _classifier._detect_contradiction(
            pane_state="idle", liveness="online"
        )
        == ""
    )


# ---------------------------------------------------------------------------
# Evidence log
# ---------------------------------------------------------------------------


def test_log_contradiction_evidence_writes_record(_isolate_state):
    _state_dir, log_path = _isolate_state
    pane_tail = "line1\nline2\nline3\n"
    written = _classifier._log_contradiction_evidence(
        agent="head-test",
        pane_state="stale",
        liveness="online",
        tmux_tail=pane_tail,
    )
    assert written == log_path
    content = log_path.read_text(encoding="utf-8")
    assert "agent=head-test" in content
    assert "note=contradiction:3rd-stale-vs-4th-green" in content
    assert "pane_state=stale" in content
    assert "liveness=online" in content
    # tail verbatim (last 40 lines — here we only have 3)
    assert "line1" in content and "line2" in content and "line3" in content


def test_log_contradiction_evidence_truncates_tail_to_40_lines(tmp_path):
    log_path = tmp_path / "contradictions.log"
    tail = "\n".join(f"L{i}" for i in range(100))
    _classifier._log_contradiction_evidence(
        agent="head-long",
        pane_state="stale",
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
            pane_state="stale",
            liveness="online",
            tmux_tail=f"tail-{i}\n",
            log_path=log_path,
        )
    content = log_path.read_text(encoding="utf-8")
    assert content.count("note=contradiction:3rd-stale-vs-4th-green") == 3
    assert "agent=agent-0" in content
    assert "agent=agent-1" in content
    assert "agent=agent-2" in content
