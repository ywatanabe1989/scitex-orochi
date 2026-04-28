---
name: orochi-62_permission-prompt-patterns-catalog
description: Permission-prompt pattern catalog (one entry per known prompt, regex + remediation). (Split from 62_permission-prompt-patterns-extras.md.)
---

> Sibling: [`79_permission-prompt-patterns-meta.md`](79_permission-prompt-patterns-meta.md) for how patterns get added, loading order, exclusions, incident log.
## Catalog

### 1. Claude Code 3-option permission menu

```yaml
- id: claude-3-option-menu
  regex: |
    Do you want to.*\n.*❯?\s*1\.\s*Yes(,|\s).*\n.*❯?\s*2\.\s*Yes,.*always allow.*\n.*❯?\s*3\.\s*No
  observed-as: |
    Do you want to proceed?
    ❯ 1. Yes
      2. Yes, and always allow ...
      3. No
  first-seen: 2026-04-15 msg#11799 (head-mba MBA sweep)
  recovery-keystroke: "2"
  rationale: |
    Option 2 is "always allow" — it accepts the action AND adds it
    to the agent's allowlist so the same prompt does not repeat
    next tick. This is the right answer for automation because
    it permanently unblocks the class of prompt without a case-
    by-case human call. Option 1 accepts this one instance but
    leaves the door open for the next matching prompt. Option 3
    is a rejection, which blocks forward motion and is almost
    never the healer's intent.
  escalation: |
    If the same session hits this pattern 3 times within 5 min
    after a "2" send, something is wrong with the allowlist
    persistence — DM the dispatcher (or post to #heads) for human call.
```

### 2. Claude Code "Esc to cancel · Tab to amend" modal

```yaml
- id: claude-esc-cancel-tab-amend
  regex: |
    Esc to cancel\s*·\s*Tab to amend
  observed-as: |
    The agent is hovering on a Claude Code permission modal that
    shows the "Esc to cancel · Tab to amend" footer. The actual
    action buttons vary above this footer.
  first-seen: 2026-04-15 msg#11855 (head-nas compound-failure incident)
  recovery-keystroke: "2"
  rationale: |
    Same as entry #1 — on current Claude Code, the 3-option menu
    footer almost always shows "Esc to cancel · Tab to amend".
    When only the footer matches but the menu body is off-screen
    in the tmux capture window, assume the 3-option pattern and
    send "2". If that's wrong, the agent will surface a new
    prompt and the next tick will classify correctly.

    **Gate**: never fire this recovery until the full capture
    (at least -S -15 lines) has been inspected for menu body.
    If the menu body shows a non-3-option variant (e.g.
    [y/N], pagination, sudo), fall through to entry #3+ or
    escalate.
  escalation: |
    If "2" Enter does not clear the modal within 5 s, the
    capture was misclassified — escalate.
```

### 3. Claude Code [y/N] single-line prompt

```yaml
- id: claude-y-n
  regex: |
    \[y/N\]\s*$|\s\[Y/n\]\s*$
  observed-as: |
    Inline y/N confirmation on a single line, typically after a
    description like "Overwrite ~/foo? [y/N]".
  first-seen: 2026-04-15 (general observation, no single incident)
  recovery-keystroke: "y\n"
  rationale: |
    **Only fire this recovery when the description text above
    the prompt matches an allowlist of known-safe actions**
    (e.g. "Overwrite", "Create directory", "Continue"). For
    destructive actions ("Delete", "Force push", "Drop
    database"), the healer must NOT auto-confirm — escalate
    instead. The allowlist lives in
    `safe-y-n-prefixes.md` as a separate skill (TBD, growing
    alongside this catalog).
  escalation: |
    Any y/N prompt where the description does not match the
    allowlist → immediate escalation, never auto-confirm.
```

### 4. Paste-buffer-unsent pseudo-prompt

```yaml
- id: paste-buffer-unsent
  regex: |
    \[Pasted text #\d+\s\+?\d+\s*lines\]
  observed-as: |
    The prompt area shows a "[Pasted text #N +M lines]" marker
    indicating the agent pasted content into the prompt but
    never submitted it. Observed 2026-04-15 across multiple
    agents during the MBA sweep (5 agents) and the NAS sweep
    (mamba-healer-nas, ~2.5 h wedge).
  first-seen: 2026-04-15 msg#11799 (head-mba MBA sweep, 5 panes)
  recovery-keystroke: "\n"   # (Enter)
  rationale: |
    The paste is in the agent's own input buffer waiting to be
    submitted. Sending Enter submits it as-is. Safe because the
    paste was composed by the agent itself (or by a user-
    controlled tool earlier in the session), not by the healer —
    the healer is only providing the "submit" keystroke that was
    missing. Never modify the paste, only submit it.

    **Critical constraint** (todo-manager msg#11809): fire ONLY
    when the pane has been *static* (no new output) for > 30 s
    AND the `[Pasted text ...]` marker is at prompt level (end
    of the tmux capture). If the agent is mid-composition, do
    not fire.
  escalation: |
    If the same session hits this pattern 3 times within 10 min,
    the agent is not consuming its own pasted input (deeper
    issue) — DM the dispatcher (or post to #heads) with the pane capture.
```

### 5. Claude Code "Press Enter to continue" pagination

```yaml
- id: claude-press-enter-to-continue
  regex: |
    Press Enter to continue|--More--
  observed-as: |
    Pager / long-output gating (typical for `man`, `less`, or
    Claude Code's own long-output mode).
  first-seen: 2026-04-15 (general observation)
  recovery-keystroke: "\n"   # (Enter, or "q" for some pagers)
  rationale: |
    This is a display-level gate, not a permission prompt. The
    keystroke is purely "advance the pager" and has no semantic
    side effect. Safe to fire unconditionally.
  escalation: |
    If sending Enter does not clear the pager within 5 s, the
    pane is wedged on something else; fall through to entry #6.
```

### 6. Claude Code long-silence (no obvious pattern)

```yaml
- id: claude-long-silence-unknown
  regex: ~   # no match — this is a fallback state, not a pattern
  observed-as: |
    The pane has been static for > 2 min, no new output, no
    known-pattern match, but the agent is not responding to
    DM pings either.
  first-seen: always
  recovery-keystroke: null   # no automated recovery
  rationale: |
    When nothing in this catalog matches and the pane is just
    silent, the healer must NOT fire a blind keystroke. The
    fallback is to escalate to the recovery playbook's §7.4
    (tmux-stuck recovery, kill-respawn) OR to §7.3 (/compact)
    based on context_pct, not to guess-and-send.
  escalation: |
    Always escalate. This entry exists in the catalog only to
    make "unknown silence" an explicit classification rather
    than a gap in the matcher. The worker reads this entry as
    "there is no recovery keystroke, hand off to §7.3 or §7.4".
```

