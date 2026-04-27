"""Regex tests for _collect_agent_metadata._pane.parse_orochi_subagent_count.

Pin the "N local agent(s) running" marker so the heartbeat sidecar
payload's ``orochi_subagent_count`` field stays reliable across Claude Code
status-line variants (singular / plural / "still running" / chat-text
with no marker).
"""

from __future__ import annotations

import sys
from pathlib import Path

# The _collect_agent_metadata package lives under scripts/client/ and isn't
# installed into site-packages — make it importable for this test.
_AGENT_META_DIR = Path(__file__).resolve().parents[1] / "scripts" / "client"
if str(_AGENT_META_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_META_DIR))

from _collect_agent_metadata._pane import parse_orochi_subagent_count  # noqa: E402


def test_single_agent_singular():
    pane = "doing some work\n  ✶ 1 local agent running · 2s\n❯ "
    assert parse_orochi_subagent_count(pane) == 1


def test_three_agents_plural():
    pane = "  ✶ 3 local agents running · 12s\n"
    assert parse_orochi_subagent_count(pane) == 3


def test_still_running_singular():
    pane = "prompt output\n  ✢ 1 local agent still running · 1m 4s\n"
    assert parse_orochi_subagent_count(pane) == 1


def test_still_running_plural():
    pane = "  ✢ 5 local agents still running · 45s\n"
    assert parse_orochi_subagent_count(pane) == 5


def test_zero_agents_plural():
    # Claude Code does surface "0 local agents running" briefly while a
    # batch of Agents winds down; keep parsing it as 0 (not as "no
    # marker").
    pane = "  0 local agents running\n"
    assert parse_orochi_subagent_count(pane) == 0


def test_no_marker_returns_zero():
    pane = "regular chat output\nnothing special here\n❯ "
    assert parse_orochi_subagent_count(pane) == 0


def test_empty_pane_returns_zero():
    assert parse_orochi_subagent_count("") == 0
    assert parse_orochi_subagent_count(None) == 0  # type: ignore[arg-type]


def test_chat_mentioning_local_agent_no_false_positive():
    # Old substring regex (``(\d+) local agent``) would fire on chat
    # prose like "2 local agent names are stale" — anchor to the
    # ``running`` trailer so that no longer happens.
    pane = "reviewing 2 local agent names that were stale last cycle\n"
    assert parse_orochi_subagent_count(pane) == 0


def test_multiple_markers_returns_first_match():
    # In practice only one marker is live at a time, but if the pane
    # scrollback contains an older marker above a newer one the
    # regex finds the first match (top-to-bottom) — acceptable because
    # heartbeat cycles are short and the top-most marker reflects the
    # earliest still-visible state. Just pin the behaviour so a future
    # refactor doesn't silently change it.
    pane = "  ✶ 2 local agents running\n... later ...\n  ✢ 4 local agents still running\n"
    assert parse_orochi_subagent_count(pane) == 2
