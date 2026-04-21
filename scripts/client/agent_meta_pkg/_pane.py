"""tmux pane capture and tail filtering for agent_meta.collect()."""

from __future__ import annotations

import re
import subprocess


def _is_channel_inbound_line(s: str) -> bool:
    """ywatanabe msg#10657 / #10677: incoming Orochi channel pushes
    appear in the pane as `← scitex-orochi · sender: ...` (then
    wrapped continuation, then `⎿ ...` reaction/result indent lines).
    These are NOT agent activity — they're fan-out from other agents
    — but they change the pane each tick so a hash-diff "is this
    agent moving?" check sees them as activity and reports the agent
    as healthy when it's actually wedged. The CLEAN view filters
    them out so stuck-detection / classifier work on agent output
    only. The RAW view keeps them so we can still verify "WS still
    delivering messages" as a separate signal."""
    if "← scitex-orochi" in s:
        return True
    # The two-line wrapped continuation of `← scitex-orochi` blocks
    # often starts with whitespace + ⎿ indent; treat those as inbound
    # too. Loose match — false-positive on legit `⎿  Done` is
    # acceptable since clean view is for diff-based stuck check, not
    # for full-fidelity rendering.
    if s.startswith("⎿"):
        return True
    return False


def capture_pane(agent: str, multiplexer: str) -> str:
    """Capture the agent's tmux pane scrollback (last 500 lines).

    Returns "" for non-tmux sessions or any tmux failure.
    """
    if multiplexer != "tmux":
        return ""
    # todo#47 — bump scrollback depth from 30 to 500 lines so the
    # hub detail endpoint can expose a ``pane_tail_full`` field for
    # the web-terminal viewer. The ~10-line ``pane_tail_block``
    # keeps its original semantics below (stuck-detection + compact
    # UI), so classifiers aren't perturbed. The full view is the
    # new user-facing surface.
    return subprocess.run(
        ["tmux", "capture-pane", "-t", agent, "-p", "-J", "-S", "-500", "-E", "-"],
        capture_output=True,
        text=True,
    ).stdout


def filter_pane_tail(pane: str) -> tuple[str, str, str, str]:
    """Filter raw pane scrollback into the four tail variants used downstream.

    Returns ``(pane_tail, pane_tail_block, pane_tail_block_clean,
    pane_tail_full)``.

    - pane_tail              — last interesting single line (legacy field)
    - pane_tail_block        — last ~10 interesting lines, raw (keeps
      channel inbound for WS-alive proof)
    - pane_tail_block_clean  — same as block but stripped of channel
      inbound (for stuck-detection / state classifier)
    - pane_tail_full         — up to 500 filtered lines, trimmed to 32 KB
      (todo#47 web-terminal tier)
    """
    pane_tail = ""
    pane_tail_block = ""
    pane_tail_block_clean = ""
    pane_tail_full = ""
    if not pane:
        return pane_tail, pane_tail_block, pane_tail_block_clean, pane_tail_full

    kept: list[str] = []
    kept_clean: list[str] = []
    kept_full: list[str] = []
    for raw_line in reversed(pane.splitlines()):
        stripped = raw_line.strip()
        if not stripped:
            continue
        # Skip the box-drawing chrome and hint banners.
        if stripped.startswith("─") or stripped.startswith("⏵"):
            continue
        if "bypass permissions on" in stripped:
            continue
        if stripped.startswith("↑↓") or stripped.startswith("Esc to"):
            continue
        line = stripped[:160]
        # Full view keeps every interesting line up to the scrollback
        # cap we captured (500 lines). 32 KB is a generous ceiling —
        # well under WS frame limits, but enough for ~400-line Claude
        # Code transcripts with long MCP tool outputs.
        if len(kept_full) < 500:
            kept_full.append(line)
        if len(kept) < 10:
            kept.append(line)
            if not _is_channel_inbound_line(line):
                kept_clean.append(line)
        if len(kept_full) >= 500:
            break
    if kept:
        pane_tail = kept[0]
        pane_tail_block = "\n".join(reversed(kept))
        # Trim clean to its own 10-line cap to match pane_tail_block size.
        pane_tail_block_clean = "\n".join(reversed(kept_clean[:10]))
    if kept_full:
        pane_tail_full = "\n".join(reversed(kept_full))
        # Hard-cap the payload so a pathological pane can't bloat the
        # heartbeat. Trim from the head (oldest) so the tail (latest
        # activity) is preserved.
        if len(pane_tail_full) > 32 * 1024:
            pane_tail_full = pane_tail_full[-32 * 1024 :]
    return pane_tail, pane_tail_block, pane_tail_block_clean, pane_tail_full


_SUBAGENT_MARKER_RE = re.compile(
    r"(\d+)\s+local\s+agents?(?:\s+still)?\s+running",
    re.IGNORECASE,
)


def parse_subagent_count(pane: str) -> int:
    """Return the subagent count advertised by Claude Code's status marker.

    Claude Code emits a line of the form ``N local agent(s) running`` (or
    ``... still running``) in the tmux pane while subagent ``Agent`` calls
    are in flight. Parse that as the authoritative count; anything else
    (no marker, empty pane) is reported as ``0`` so the hub's
    ``subagent_count`` field stays a monotonic "how many sub-Agents does
    this pane think it has right now" indicator. Anchoring to the literal
    ``running`` trailer avoids false positives from chat text that merely
    mentions "local agent".
    """
    if not pane:
        return 0
    m = _SUBAGENT_MARKER_RE.search(pane)
    return int(m.group(1)) if m else 0
