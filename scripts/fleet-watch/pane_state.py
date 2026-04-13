#!/usr/bin/env python3
"""Claude Code tmux pane state classifier (todo follow-up to msg#9438/9442).

Mirrors the canonical state taxonomy from
``~/.emacs.d/lisp/emacs-claude-code/src/ecc-state-detection.el``
(github.com/ywatanabe1989/emacs-claude-code) and extends it with a
small set of Orochi-fleet-specific blocking states.

Canonical states (mirror of elisp module — DO NOT diverge):
    :y/y/n        — 3-choice permission prompt (Yes / Yes-and / No)
    :y/n          — 2-choice permission prompt (Yes / No)
    :suggestion   — edit suggestion (↵ send hint)
    :running      — Claude is generating
    :user-typing  — user has typed a char after the prompt prefix
    :waiting      — Claude is finished, ready for next input
                    (matches "Cooked for", "Crunched for", "❯ ", etc.)

Orochi extension states (blocking — checked BEFORE canonical states):
    :quota_exhausted    — anthropic quota cap, /extra-usage required
    :auth_error         — credentials invalid, /login required
    :mcp_broken         — MCP server not configured, restart needed
    :shell_only         — Claude not running, raw shell prompt
    :context_warning    — "/clear to save Nk tokens" hint visible
    :idle_with_paste    — `❯ [Pasted text #N +M lines]` queued, never sent

Recommended actions per state (mirror of elisp ecc-auto-response.el +
Orochi additions):
    :y/n              → send "1"
    :y/y/n            → send "2"
    :waiting          → /speak-signature (or assign work)
    :running          → leave alone
    :user-typing      → leave alone (user owns the prompt)
    :suggestion       → leave alone
    :idle_with_paste  → escalate (paste > 2 cycles old → send Enter)
    :context_warning  → schedule /compact at next safe boundary
    :quota_exhausted  → swap credential file + interactive /login
    :auth_error       → swap credential file + interactive /login
    :mcp_broken       → restore .mcp.json + restart agent
    :shell_only       → restart agent via scitex-agent-container

Usage:
    pane_state.py <file>          # human format
    pane_state.py --json <file>   # JSON
    pane_state.py --all <dir>     # iterate *.txt in dir

Stdlib only. Runs over SSH and on every fleet host.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

# Mirror of --ecc-state-detection-buffer-size (elisp). The canonical
# state lives in the LAST N chars of the pane — never scan scrollback.
TAIL_CHARS = 2048

# ---------------------------------------------------------------------------
# Canonical pattern catalog — mirrors emacs-claude-code/ecc-state-detection.el
# Keep in sync. AGENTS MUST NOT silently diverge from the elisp patterns.
# ---------------------------------------------------------------------------

WAITING_PATTERNS: tuple[str, ...] = (
    "Crunched for",
    "Sautéed for",
    "Cogitated for",
    "Whipped up",
    "Brewed for",
    "Cooked for",
    "Marinated for",
    "Stewed for",
    "Baked for",
    "Simmered for",
    "Crafted for",
    "Distilled for",
    "❯ ",
    "› ",  # Codex
)

RUNNING_PATTERNS: tuple[str, ...] = (
    "(esc to interrupt",
    "tokens ·",
    "· thinking",
    "ing…",          # catches Boogieing… Thundering… Mulling… etc.
    "· thought for ",
    "• esc to interrupt)",  # Codex
)

YN_PATTERNS: tuple[str, ...] = (
    "❯ 1. Yes",
    "› 1. Yes, proceed (y)",  # Codex
)

YYN_PATTERNS: tuple[str, ...] = (
    "2. Yes, and",
    "2. Yes, allow",
    "2. Yes, auto-accept",
    "2. Yes, don't ask",
    "2. Yes, and don't",
)

SUGGESTION_PATTERNS: tuple[str, ...] = (
    "↵ send",
)

# ---------------------------------------------------------------------------
# Orochi fleet extension states — blocking conditions to detect BEFORE
# the canonical taxonomy. These are not part of emacs-claude-code; they
# come from real fleet samples (msg#9430).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExtRule:
    state: str
    patterns: tuple[str, ...]
    severity: str
    action: str

EXTENSION_RULES: tuple[ExtRule, ...] = (
    ExtRule(
        state=":mcp_broken",
        patterns=(
            r"no MCP server configured with that name",
        ),
        severity="blocked",
        action="restore .mcp.json template + restart Claude (todo#287)",
    ),
    ExtRule(
        state=":auth_error",
        patterns=(
            r"API Error:\s*401",
            r"authentication_error",
            r"Invalid authentication credentials",
            r"Please run /login",
        ),
        severity="blocked",
        action="credential file invalid — swap .credentials.json + interactive /login",
    ),
    ExtRule(
        state=":quota_exhausted",
        patterns=(
            r"You're out of extra usage",
            r"Limit reached \(resets",
            r"⚠ Limit reached",
            r"/extra-usage to finish",
        ),
        severity="blocked",
        action="anthropic quota cap — wait for reset OR swap to alternate credential file",
    ),
    ExtRule(
        state=":idle_with_paste",
        patterns=(
            r"❯\s*\[Pasted text #\d+",
        ),
        severity="warn",
        action="user pasted text but never hit Enter — send Enter (or escalate)",
    ),
    ExtRule(
        state=":context_warning",
        patterns=(
            r"new task\? /clear to save \d+(\.\d+)?k tokens",
        ),
        severity="warn",
        action="context filling — schedule /compact at next safe boundary",
    ),
)

# ---------------------------------------------------------------------------
# Action map — mirrors --ecc-auto-response-responses + Orochi additions
# ---------------------------------------------------------------------------

ACTION_MAP: dict[str, str] = {
    # Canonical (from ecc-auto-response.el)
    ":y/n":           "send '1'",
    ":y/y/n":         "send '2'",
    ":waiting":       "/speak-signature OR assign work (idle ready)",
    ":running":       "leave alone — model is generating",
    ":user-typing":   "leave alone — user owns the prompt",
    ":suggestion":    "leave alone — edit suggestion in flight",
    # Orochi extensions
    ":mcp_broken":     "restore .mcp.json + restart agent",
    ":auth_error":     "swap credential file + interactive /login",
    ":quota_exhausted": "swap credential file (e.g. .credentials-ywata1989.json) + /login",
    ":idle_with_paste": "send Enter (if old) or escalate to ywatanabe",
    ":context_warning": "/compact at next safe boundary",
    ":shell_only":     "restart agent via scitex-agent-container",
    ":unknown":        "no pattern matched — capture sample and update catalog",
}


@dataclass
class Classification:
    state: str
    severity: str
    action: str
    matched_pattern: str | None
    matched_text: str | None
    has_claude_box: bool
    extras: dict = field(default_factory=dict)


def _normalize(text: str) -> str:
    """Mirror of --ecc-state-detection--normalize-text."""
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[\u2000-\u200b\u202f\u205f\u3000]", " ", text)
    return text


def _tail(text: str, n: int = TAIL_CHARS) -> str:
    return text[-n:] if len(text) > n else text


def _has_claude_box(text: str) -> bool:
    """Detect the bracketed Claude input box `─── ❯ ───`."""
    return "❯" in text and "──" in text


def _last_nonempty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line
    return ""


# Footer / chrome lines we ignore when looking for the active prompt line.
_PROMPT_CHROME_RE = re.compile(
    r"^(\s*$|\s*─+\s*$|\s*⏵⏵|\s*\[Opus|\s*\[Sonnet|\s*\[Haiku|"
    r"\s*✗ Auto-update|\s*new task\?|\s*Tip:)"
)


def _find_prompt_line(tail: str, look_back: int = 12) -> str | None:
    """Scan the last `look_back` non-chrome lines for a `❯ `/`› ` line.
    Returns the first match (most recent prompt input area)."""
    lines = tail.splitlines()
    seen = 0
    for line in reversed(lines):
        if _PROMPT_CHROME_RE.match(line):
            continue
        seen += 1
        norm = _normalize(line).rstrip()
        if norm.startswith("❯ ") or norm.startswith("❯") or norm.startswith("› "):
            return norm
        if seen >= look_back:
            break
    return None


def _user_typing(tail: str) -> str | None:
    """If the active prompt line is `❯ <printable>`, user is typing.
    Mirror of --ecc-state-detection--user-typing-p, but scans past footer
    chrome to find the real prompt line."""
    line = _find_prompt_line(tail)
    if not line:
        return None
    for prefix in ("❯ ", "› "):
        if line.startswith(prefix) and len(line) > len(prefix):
            ch = line[len(prefix)]
            if 33 <= ord(ch) <= 126:
                return prefix + ch
    return None


def _extras(text: str) -> dict:
    extras: dict = {}
    m = re.search(r"(\d+)%\s*\|", text)
    if m:
        extras["context_pct"] = int(m.group(1))
    m = re.search(r"\|\s*([\w.+-]+@[\w.-]+)", text)
    if m:
        extras["account_email"] = m.group(1)
    m = re.search(r"(?:Cooked|Crunched|Brewed|Stewed|Baked) for\s*(\d+m\s*\d+s|\d+s)", text)
    if m:
        extras["last_burst_duration"] = m.group(1)
    m = re.search(r"\[Pasted text #\d+\s*\+(\d+)\s*lines\]", text)
    if m:
        extras["queued_paste_lines"] = int(m.group(1))
    if "out of extra usage" in text or "Limit reached" in text:
        m = re.search(r"resets ([^)\n]+?)(?:\)|$)", text)
        if m:
            extras["quota_resets"] = m.group(1).strip()
    return extras


def _match_any(patterns, text: str) -> str | None:
    for p in patterns:
        if p in text:
            return p
    return None


def _match_any_re(patterns, text: str) -> tuple[str | None, str | None]:
    for p in patterns:
        m = re.search(p, text)
        if m:
            return p, m.group(0)[:120]
    return None, None


def classify(pane_text: str) -> Classification:
    """Classify a tmux pane capture.

    Order of evaluation (highest priority first):
      0. shell_only   — no Claude input box at all
      1. mcp_broken   — Orochi extension (terminal)
      2. auth_error   — Orochi extension (terminal)
      3. quota_exhausted — Orochi extension (terminal)
      4. y/y/n        — canonical permission (3-way)
      5. suggestion   — canonical edit hint
      6. y/n          — canonical permission (2-way)
      7. running      — canonical busy
      8. user-typing  — user has chars at prompt (incl. paste markers)
      9. idle_with_paste — Orochi extension (special user-typing variant)
     10. context_warning — Orochi extension (advisory)
     11. waiting     — canonical idle / ready for input
     12. unknown     — fallback
    """
    text = _normalize(pane_text)
    tail = _tail(text)
    has_box = _has_claude_box(text)
    extras = _extras(text)

    # 0 — shell-only (no Claude UI)
    if not has_box:
        return Classification(
            state=":shell_only",
            severity="blocked",
            action=ACTION_MAP[":shell_only"],
            matched_pattern=None,
            matched_text=None,
            has_claude_box=False,
            extras=extras,
        )

    # 1-3 — Orochi blocking extensions (regex, last 2K chars only)
    for rule in EXTENSION_RULES[:3]:  # mcp_broken, auth_error, quota_exhausted
        pat, mt = _match_any_re(rule.patterns, tail)
        if pat:
            return Classification(
                state=rule.state,
                severity=rule.severity,
                action=rule.action,
                matched_pattern=pat,
                matched_text=mt,
                has_claude_box=True,
                extras=extras,
            )

    # 4 — y/y/n (canonical, highest among interactive)
    p = _match_any(YYN_PATTERNS, tail)
    if p:
        return Classification(
            state=":y/y/n", severity="needs_human",
            action=ACTION_MAP[":y/y/n"],
            matched_pattern=p, matched_text=p,
            has_claude_box=True, extras=extras,
        )

    # 5 — suggestion
    p = _match_any(SUGGESTION_PATTERNS, tail)
    if p:
        return Classification(
            state=":suggestion", severity="ok",
            action=ACTION_MAP[":suggestion"],
            matched_pattern=p, matched_text=p,
            has_claude_box=True, extras=extras,
        )

    # 6 — y/n
    p = _match_any(YN_PATTERNS, tail)
    if p:
        return Classification(
            state=":y/n", severity="needs_human",
            action=ACTION_MAP[":y/n"],
            matched_pattern=p, matched_text=p,
            has_claude_box=True, extras=extras,
        )

    # 7 — running
    p = _match_any(RUNNING_PATTERNS, tail)
    if p:
        return Classification(
            state=":running", severity="ok",
            action=ACTION_MAP[":running"],
            matched_pattern=p, matched_text=p,
            has_claude_box=True, extras=extras,
        )

    # 8/9 — user-typing  (Orochi `idle_with_paste` is a sub-case)
    typing = _user_typing(tail)
    if typing:
        prompt_line = _find_prompt_line(tail) or ""
        # Sub-classify: is it a paste marker?
        if "[Pasted text #" in prompt_line:
            rule = next(r for r in EXTENSION_RULES if r.state == ":idle_with_paste")
            return Classification(
                state=":idle_with_paste",
                severity=rule.severity,
                action=rule.action,
                matched_pattern=rule.patterns[0],
                matched_text=_last_nonempty_line(tail)[:120],
                has_claude_box=True,
                extras=extras,
            )
        return Classification(
            state=":user-typing", severity="ok",
            action=ACTION_MAP[":user-typing"],
            matched_pattern=typing, matched_text=typing,
            has_claude_box=True, extras=extras,
        )

    # 10 — context_warning (advisory, can coexist with waiting)
    pat, mt = _match_any_re(
        next(r for r in EXTENSION_RULES if r.state == ":context_warning").patterns,
        tail,
    )
    if pat:
        return Classification(
            state=":context_warning", severity="warn",
            action=ACTION_MAP[":context_warning"],
            matched_pattern=pat, matched_text=mt,
            has_claude_box=True, extras=extras,
        )

    # 11 — waiting (canonical idle)
    p = _match_any(WAITING_PATTERNS, tail)
    if p:
        return Classification(
            state=":waiting", severity="ok",
            action=ACTION_MAP[":waiting"],
            matched_pattern=p, matched_text=p,
            has_claude_box=True, extras=extras,
        )

    # 12 — unknown
    return Classification(
        state=":unknown", severity="warn",
        action=ACTION_MAP[":unknown"],
        matched_pattern=None, matched_text=None,
        has_claude_box=True, extras=extras,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _format_human(name: str, c: Classification) -> str:
    bits = []
    if c.extras.get("context_pct") is not None:
        bits.append(f"ctx={c.extras['context_pct']}%")
    if c.extras.get("account_email"):
        bits.append(f"acct={c.extras['account_email']}")
    if c.extras.get("queued_paste_lines"):
        bits.append(f"paste={c.extras['queued_paste_lines']}L")
    if c.extras.get("last_burst_duration"):
        bits.append(f"last={c.extras['last_burst_duration']}")
    if c.extras.get("quota_resets"):
        bits.append(f"resets={c.extras['quota_resets']}")
    extras_s = " ".join(bits)
    head = f"{name:<50} {c.severity:<12} {c.state:<20} {extras_s}"
    if c.severity in ("blocked", "needs_human", "warn"):
        return f"{head}\n  → {c.action}"
    return head


def main(argv: list[str]) -> int:
    json_mode = "--json" in argv
    all_mode = "--all" in argv
    args = [a for a in argv[1:] if not a.startswith("--")]
    if not args:
        print("usage: pane_state.py [--json] [--all] <file-or-dir>", file=sys.stderr)
        return 2

    target = Path(args[0])
    if all_mode or target.is_dir():
        targets = sorted(target.glob("*.txt")) if target.is_dir() else [target]
    else:
        targets = [target]

    results: dict = {}
    for t in targets:
        try:
            text = t.read_text(errors="replace")
        except OSError as e:
            print(f"ERR {t}: {e}", file=sys.stderr)
            continue
        c = classify(text)
        results[t.name] = asdict(c)
        if not json_mode:
            print(_format_human(t.name, c))

    if json_mode:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
