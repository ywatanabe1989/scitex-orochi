"""Agent decision-transparency pane-state classifier (todo#418).

Mirrors the state labels the fleet-prompt-actuator +
scitex_agent_container.runtimes.prompts module use, but inlined so
agent_meta stays dependency-free. The classifier runs on every push
(~30 s), reads the pane tail, and emits a stable label + verbatim
stuck-prompt text so the hub Agents tab can render a badge + expand
the prompt ywatanabe needs to see.

2026-04-21 extension (lead msg#15541): added `stale` orochi_pane_state and a
contradiction detector for the "3rd LED = stale while 4th LED = green"
case observed on the dashboard. Contradiction evidence gets written to
a dedicated log so future pattern additions have ground-truth data.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

_COMPOSE_CHEVRON = "❯"
_PROGRESS_MARKERS = ("esc to interrupt",)
_AUTH_MARKERS = ("/login", "Invalid API key", "authentication failed")
_BYPASS_MARKERS = ("Bypass Permissions", "2. Yes, I accept")
_DEVCHAN_MARKERS = ("1. I am using this for local development",)
_YN_MARKERS = ("y/n", "[y/N]", "[Y/n]")

# ---------------------------------------------------------------------------
# Busy-marker groups (2026-04-21 expansion, fix/classifier-busy-markers-expand)
#
# Previously this was one opaque tuple of literal substrings. The
# contradiction-log evidence from `~/.local/state/scitex/fleet-pane-
# contradictions.log` (81 KB on head-mba, 480 KB on head-ywata-note-win)
# showed several false-positive stale classifications where the pane
# tail was byte-identical across cycles *but the agent was alive and
# deliberating*. The fix is to split the marker set into documented
# groups — each rationale-commented — so future additions have a clear
# home and tests can target one group at a time.
#
# Semantics: any match in ANY group => pane is NOT stale.
# ---------------------------------------------------------------------------

# Group A: Claude Code spinner present-tense gerunds.
# Rationale: the CC TUI rotates through a fixed set of "‑ing" verbs
# while the model is streaming tokens. Observed variants include
# Mulling / Pondering / Churning / Roosting / Thinking / Cogitating /
# Musing / Reflecting / Working / Contemplating / Deliberating /
# Considering / Analysing / Brewing / Baking / Cooking / Crunching.
# We keep the bare form (no ellipsis) because tmux capture sometimes
# drops the trailing … when wrapping.
_BUSY_SPINNER_GERUNDS = (
    "Mulling",
    "Pondering",
    "Churning",
    "Roosting",
    "Thinking",
    "Cogitating",
    "Musing",
    "Reflecting",
    "Working",
    "Contemplating",
    "Deliberating",
    "Considering",
    "Analysing",
    "Analyzing",
    "Brewing",
    "Baking",
    "Cooking",
    "Crunching",
    "Simmering",
    "Percolating",
    "Noodling",
    "Ruminating",
)

# Group B: Claude Code spinner past-tense "X for Ns" lines.
# Rationale: immediately AFTER a streaming burst completes the TUI
# shows `✻ Baked for 40s`, `✻ Brewed for 35s`, `✻ Cogitated for 39s`,
# `✻ Cooked for 1m 28s` etc. This line is static (doesn't change until
# the next turn) but absolutely indicates a live agent that just
# finished thinking — a prime false-positive source for `stale`.
# Observed verbatim in log: `Baked for`, `Brewed for`, `Cogitated for`,
# `Cooked for`. Matched as substrings (no regex) because the duration
# suffix varies.
_BUSY_SPINNER_PAST_TENSE = (
    "Baked for",
    "Brewed for",
    "Cogitated for",
    "Cooked for",
    "Mulled for",
    "Pondered for",
    "Churned for",
    "Roosted for",
    "Thought for",
    "Mused for",
    "Reflected for",
    "Worked for",
    "Contemplated for",
    "Deliberated for",
    "Considered for",
    "Analysed for",
    "Analyzed for",
    "Crunched for",
    "Crunched",
    "Simmered for",
    "Percolated for",
    "Noodled for",
    "Ruminated for",
)

# Group C: "N local agent(s) still running" — strong liveness signal.
# Rationale: the CC TUI footer shows this when the user has dispatched
# `Agent(...)` orochi_subagents that are still working. Static text but the
# main session is very much alive, just waiting on children.
_BUSY_SUBAGENT_MARKERS = (
    "local agent still running",
    "local agents still running",
    "Backgrounded agent",
)

# Group D: TodoWrite / task-list static views.
# Rationale: the #1 false-positive class from the contradiction log.
# When the agent renders its task list (`TodoWrite` output) the pane
# looks like:
#     1 tasks (0 done, 1 in progress, 0 open)
#     ◼ pane-state classifier: 3rd-stale vs 4th-green contradiction dete…
# The text is perfectly static between cycles (nothing animates) but
# the agent is mid-deliberation. We match this via regex — the opaque
# literal-substring approach can't handle the numeric variance.
# The `_BUSY_ANIMATION_REGEXES` tuple below holds compiled patterns.
_BUSY_TASK_LIST_MARKERS = (
    # "◼" checkbox bullet is the distinctive TodoWrite in-progress glyph.
    # Its presence anywhere in the scan window means the agent is
    # tracking work — treat as alive.
    "◼ ",
)

# Group E: regex patterns for busy markers that vary numerically /
# temporally. Each entry: (compiled_pattern, human_rationale).
_BUSY_ANIMATION_REGEXES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\d+\s+tasks?\s+\(\d+\s+done,\s+\d+\s+in\s+progress"),
        "TodoWrite task-list header: 'N tasks (M done, K in progress...)'",
    ),
    (
        re.compile(r"[✻✽✶✳✢✣]\s+[A-Z][a-z]+(?:ed|ted|ked|wed|ned|med|sed)\s+for\s+\d"),
        "Claude Code past-tense spinner with star glyph ('✻ Baked for 40s')",
    ),
    (
        re.compile(r"[✻✽✶✳✢✣]\s+[A-Z][a-z]+(?:ing|ling|ning|ming|ting|king)\b"),
        "Claude Code present-tense spinner with star glyph ('✻ Mulling…')",
    ),
    (
        re.compile(r"\(esc to interrupt\)"),
        "Streaming-in-progress hint (redundant with _PROGRESS_MARKERS but cheap)",
    ),
    (
        re.compile(r"Press up to edit queued messages?"),
        "Queued-message hint — implies active session with pending work",
    ),
)

# Consolidated literal-substring marker tuple (A + B + C + D + legacy).
# Kept as a module-level attribute for back-compat with any caller that
# imports `_BUSY_ANIMATION_MARKERS` directly (e.g. tests).
_BUSY_ANIMATION_MARKERS: tuple[str, ...] = (
    *_BUSY_SPINNER_GERUNDS,
    *(f"{g}…" for g in _BUSY_SPINNER_GERUNDS),
    *(f"{g}..." for g in _BUSY_SPINNER_GERUNDS),
    *_BUSY_SPINNER_PAST_TENSE,
    *_BUSY_SUBAGENT_MARKERS,
    *_BUSY_TASK_LIST_MARKERS,
    "Press up to edit queued messages",
)

# Where we persist pane-tail hashes across classifier calls so we can
# detect "this pane has not changed in N cycles" without adding
# cross-process state to the payload. Keyed by agent name. Cheap enough
# to live next to the other agent_meta state files.
_STATE_DIR = Path(
    os.environ.get(
        "SCITEX_FLEET_CLASSIFIER_STATE_DIR",
        str(Path.home() / ".local" / "state" / "scitex" / "fleet-classifier"),
    )
)

# Where contradiction-evidence records land. One line per occurrence,
# timestamped, with a verbatim tail of the tmux pane so ywatanabe (and
# future pattern work) can see exactly what the agent was showing when
# the classifier disagreed with the heartbeat.
_CONTRADICTIONS_LOG = Path(
    os.environ.get(
        "SCITEX_FLEET_CONTRADICTIONS_LOG",
        str(
            Path.home()
            / ".local"
            / "state"
            / "scitex"
            / "fleet-pane-contradictions.log"
        ),
    )
)

# Cycles of identical pane tail before we flip the classifier to
# `stale`. The agent_meta push cycle is ~30 s, so 3 cycles ≈ 90 s of
# no visible change — that's comfortably longer than a burst of silent
# token streaming but shorter than the HB `stale` threshold (10 min),
# so the 3rd-LED contradiction window is wide enough to catch.
_STALE_CYCLES_THRESHOLD = 3


def _extract_compose_text(tail: str) -> str:
    """Return the content after the `❯` chevron on the last compose line, or ''."""
    compose = ""
    for line in tail.splitlines()[-12:]:
        stripped = line.lstrip()
        if stripped.startswith(_COMPOSE_CHEVRON):
            rest = stripped[len(_COMPOSE_CHEVRON) :]
            compose = rest.lstrip(" \t\u00a0").rstrip()
    return compose


def _has_idle_compose_prompt(tail: str) -> bool:
    """True when the pane shows a clean empty `❯` compose prompt.

    An empty compose chevron means the agent is sitting at the prompt
    with no draft text — it is *self-reporting* "idle, ready for input"
    each cycle. The pane bytes are static (nothing animates) but the
    agent is alive and waiting. Without this signal, the digest-based
    stagnation check escalates these legitimate idle agents to `stale`.
    """
    for line in tail.splitlines()[-12:]:
        stripped = line.lstrip()
        if stripped.startswith(_COMPOSE_CHEVRON):
            rest = stripped[len(_COMPOSE_CHEVRON) :].strip()
            if not rest:
                return True
    return False


def _has_busy_animation(hay: str) -> bool:
    """True when the pane shows a busy-animation / known-alive marker.

    Checks in this order (cheapest first):
      1. Literal substrings from `_BUSY_ANIMATION_MARKERS` — the union
         of groups A (present-tense gerunds), B (past-tense "X for Ns"),
         C (subagent markers) and D (task-list bullets).
      2. Compiled regexes from `_BUSY_ANIMATION_REGEXES` — handle the
         TodoWrite task-list header and star-glyph spinner variants
         where numerics / verb tense prevent a pure literal match.

    Conservative: if *any* marker matches in the scan window we consider
    the pane busy and therefore NOT stale, even when the bytes didn't
    change between two samples. Rationale: false-negative (missing a
    busy marker) → user sees a spurious `stale` LED; false-positive
    (over-matching) → user sees a missed stall. The latter is recoverable
    via the 10-minute heartbeat timeout; the former spams the dashboard.
    """
    if any(m in hay for m in _BUSY_ANIMATION_MARKERS):
        return True
    for pattern, _rationale in _BUSY_ANIMATION_REGEXES:
        if pattern.search(hay):
            return True
    return False


def _pane_digest(tail_clean: str, full_pane: str) -> str:
    """Stable short digest of the pane content used for stagnation tracking.

    We hash `tail_clean` (channel-chatter stripped) + `full_pane` so that
    ← inbound chatter from scitex-orochi doesn't shift the digest when
    the agent itself hasn't typed / printed anything new.
    """
    h = hashlib.sha1()
    h.update((tail_clean or "").encode("utf-8", errors="replace"))
    h.update(b"\0")
    h.update((full_pane or "").encode("utf-8", errors="replace"))
    return h.hexdigest()[:16]


def _load_state(agent: str) -> tuple[str, int]:
    """Return (last_digest, consecutive_same_count) from disk for `agent`.

    Absent / unreadable state file → ('', 0). Best-effort only — a
    classifier that cannot read its state file must still classify.
    """
    if not agent:
        return "", 0
    path = _STATE_DIR / f"{agent}.state"
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return "", 0
    parts = raw.split("\t", 1)
    if len(parts) != 2:
        return "", 0
    digest = parts[0].strip()
    try:
        count = int(parts[1].strip())
    except (TypeError, ValueError):
        count = 0
    return digest, max(0, count)


def _save_state(agent: str, digest: str, count: int) -> None:
    """Persist (digest, count) for `agent`. Best-effort — never raises."""
    if not agent:
        return
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        (_STATE_DIR / f"{agent}.state").write_text(
            f"{digest}\t{count}\n", encoding="utf-8"
        )
    except OSError:
        pass


def _update_stagnation_count(agent: str, digest: str) -> int:
    """Compare `digest` to the previous digest for `agent`, update state,
    and return the new consecutive-same count. 0 means "changed this
    cycle"; N >= 1 means "unchanged for N cycles in a row"."""
    prev_digest, prev_count = _load_state(agent)
    if prev_digest and prev_digest == digest:
        count = prev_count + 1
    else:
        count = 0
    _save_state(agent, digest, count)
    return count


def _classify_orochi_pane_state(
    tail_clean: str,
    full_pane: str,
    agent: str = "",
) -> str:
    """Classify the agent's current pane state into one of:
    running / compose_pending_unsent / bypass_permissions_prompt /
    dev_channels_prompt / y_n_prompt / auth_error / stale / idle / ""

    Conservative — returns "" when we can't confidently classify.
    The full_pane string is the raw ~30-line capture used for marker
    scans; tail_clean is the channel-inbound-stripped tail used for
    compose-box detection (so ← scitex-orochi lines don't fool us).

    `agent` is optional. When supplied, the classifier tracks the
    pane-tail digest across calls and can emit `stale` when the pane
    has not changed for `_STALE_CYCLES_THRESHOLD` consecutive cycles.
    When `agent` is empty, stagnation tracking is skipped and the
    classifier behaves exactly like its pre-2026-04-21 self.
    """
    if not full_pane and not tail_clean:
        return ""
    hay = (full_pane or "") + "\n" + (tail_clean or "")
    if any(m in hay for m in _PROGRESS_MARKERS):
        return "running"
    if any(m in hay for m in _AUTH_MARKERS):
        return "auth_error"
    if all(m in hay for m in _BYPASS_MARKERS):
        return "bypass_permissions_prompt"
    if any(m in hay for m in _DEVCHAN_MARKERS):
        return "dev_channels_prompt"
    if any(m in hay for m in _YN_MARKERS):
        return "y_n_prompt"
    compose = _extract_compose_text(tail_clean)
    if len(compose) >= 3 and not compose.startswith("> "):
        return "compose_pending_unsent"

    # Stagnation check — only meaningful when we have a stable agent
    # identity to key the digest against. Skips cleanly when agent is
    # empty (legacy callers, one-shot eval in tests, etc.).
    if agent:
        digest = _pane_digest(tail_clean, full_pane)
        same_cycles = _update_stagnation_count(agent, digest)
        if same_cycles >= _STALE_CYCLES_THRESHOLD and not _has_busy_animation(hay):
            # An empty `❯ ` compose chevron is the agent self-reporting
            # "idle, ready for input" — bytes-identical across cycles by
            # design. Treat as `idle`, not `stale`. Without this carve-out,
            # any agent peacefully waiting at the prompt for >90s gets
            # ghosted on the topology canvas.
            if _has_idle_compose_prompt(tail_clean):
                return "idle"
            return "stale"
    return "idle"


def _extract_stuck_prompt(
    tail_clean: str,
    full_pane: str,
    agent: str = "",
) -> str:
    """Return the verbatim stuck-prompt text the agent is blocked on.

    Empty string when the agent isn't stuck. For `compose_pending_unsent`
    we return the chevron-line content; for the other prompt classes
    (bypass/dev-channels/y_n) we return a short excerpt from the tail
    containing the marker line, so ywatanabe can see *exactly* what text
    the agent is facing.

    `stale` is treated like a stuck state for extraction purposes — we
    hand back the tail excerpt so ywatanabe can read what the agent was
    staring at when it stopped making progress.
    """
    state = _classify_orochi_pane_state(tail_clean, full_pane, agent)
    if state in ("running", "idle", ""):
        return ""
    if state == "compose_pending_unsent":
        return _extract_compose_text(tail_clean)[:500]
    hay_lines = (tail_clean or "").splitlines()[-12:]
    return "\n".join(hay_lines)[:500]


# ---------------------------------------------------------------------------
# Contradiction detector + evidence log
# ---------------------------------------------------------------------------

_CONTRADICTION_STALE_VS_GREEN = "contradiction:3rd-stale-vs-4th-green"


def _is_liveness_green(liveness: str | None) -> bool:
    """The 4th LED (heartbeat-derived liveness) is considered `green`
    when the hub sees the agent as actively online. Any other value
    (idle / stale / offline / unknown) is NOT green."""
    return (liveness or "").strip().lower() == "online"


def _detect_contradiction(orochi_pane_state: str, liveness: str | None) -> str:
    """Return a classifier-note string when orochi_pane_state disagrees with the
    heartbeat-derived liveness in a way that ywatanabe flagged on the
    dashboard (msg#15541). Empty string otherwise.

    Current rule: orochi_pane_state == `stale` while heartbeat liveness is
    `online` (green) is a hard contradiction — the pane says nothing
    is happening but the hub is still receiving fresh heartbeats.
    """
    if (orochi_pane_state or "").strip().lower() == "stale" and _is_liveness_green(liveness):
        return _CONTRADICTION_STALE_VS_GREEN
    return ""


def _log_contradiction_evidence(
    agent: str,
    orochi_pane_state: str,
    liveness: str | None,
    tmux_tail: str,
    *,
    note: str = _CONTRADICTION_STALE_VS_GREEN,
    log_path: Path | None = None,
    max_tail_lines: int = 40,
) -> Path | None:
    """Append one evidence record to the contradictions log.

    Format (one record = multiple lines, trailer blank line):
        ---
        ts=<iso8601 utc>
        agent=<name>
        note=<classifier note>
        orochi_pane_state=<state>
        liveness=<liveness>
        tail:
        <last N lines of tmux pane, verbatim>

    Best-effort. Returns the Path written to on success, None on failure.
    The log path is configurable via SCITEX_FLEET_CONTRADICTIONS_LOG for
    tests; otherwise defaults to ~/.local/state/scitex/fleet-pane-contradictions.log.
    """
    from datetime import datetime, timezone

    target = Path(log_path) if log_path else _CONTRADICTIONS_LOG
    lines = (tmux_tail or "").splitlines()
    tail_excerpt = "\n".join(lines[-max_tail_lines:])

    record = (
        "---\n"
        f"ts={datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
        f"agent={agent}\n"
        f"note={note}\n"
        f"orochi_pane_state={orochi_pane_state}\n"
        f"liveness={liveness or ''}\n"
        "tail:\n"
        f"{tail_excerpt}\n"
        "\n"
    )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fp:
            fp.write(record)
    except OSError:
        return None
    return target
