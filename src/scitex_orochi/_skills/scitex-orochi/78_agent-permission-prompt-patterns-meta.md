---
name: orochi-61_agent-permission-prompt-patterns-meta
description: Permission-pattern meta — how new patterns get added, loading order for workers, deliberately-excluded prompts, related skills, incident log. (Split from 61_agent-permission-prompt-patterns-extras.md.)
---

> Sibling: [`61_agent-permission-prompt-patterns-catalog.md`](61_agent-permission-prompt-patterns-catalog.md) for the pattern catalog.

## How patterns get added

When a new observed prompt is NOT in the catalog, the discovery
workflow is:

1. **Capture the pane** with enough scrollback to show the full
   prompt (at least `tmux capture-pane -p -S -20`).
2. **Determine the safe keystroke** by human judgment (look at
   the options, pick the one that advances without granting
   more than needed).
3. **Draft the entry** as a 7-field YAML block matching the
   schema above. Include the exact message ID where the pattern
   was first observed (so the audit trail is preserved).
4. **Open a PR** against this file. The PR reviewer's job is to
   confirm the regex actually matches the observed capture and
   does not false-positive on other prompts. Add a test capture
   as a code block in the PR body for the reviewer to eyeball.
5. **Do NOT** rush — a wrong regex or wrong keystroke here
   becomes automation that lies to every healer in the fleet.
   Prefer caution and escalation over premature automation.

The catalog is a **living document**. Every new prompt variant
Claude Code ships (new wording, new option ordering, new modal
style) becomes a new entry here. operator msg#11779 frames this
as "pattern accumulation matters more than the automation rush"
— stay slow and safe on additions, fast on escalation when
nothing matches.

## Loading order for workers

At worker (mamba-healer-<host>) boot, load entries in order and
match the first one that fires:

1. `paste-buffer-unsent` (most specific, prompt-level marker)
2. `claude-3-option-menu` (specific menu body)
3. `claude-esc-cancel-tab-amend` (less specific, footer only)
4. `claude-press-enter-to-continue` (pager)
5. `claude-y-n` (only with allowlisted prefix)
6. `claude-long-silence-unknown` (fallback, always escalates)

Precedence matters because the paste-buffer-unsent marker can
coexist with the "Esc to cancel" footer (if the agent pasted
into a prompt that's now showing a modal). In that case, the
paste is the underlying blocker and the modal is downstream of
the paste being submitted — fire the paste recovery first, then
re-classify on the next tick.

## Deliberately NOT in the catalog

These prompts are excluded on purpose; the healer must NEVER
auto-recover them:

- **"Really delete? [y/N]"** — destructive, must escalate.
- **"Force push? [y/N]"** — destructive, must escalate.
- **"Send email? [y/N]"** — outbound-visible side effect, must
  escalate.
- **"Run this remote script? [y/N]"** — supply-chain risk, must
  escalate.
- **Anything containing `sudo`, `rm -rf`, `git reset --hard`,
  `DROP TABLE`, `kubectl delete`** — escalate, even if the rest
  of the prompt looks like a known-safe pattern.

If a new observed prompt looks even vaguely destructive, the
PR to add it to this catalog is automatically rejected — the
right place for that class of prompt is a human-call escalation,
not a regex.

## Related skills

- `fleet-health-daemon-design.md` — §7.1 (permission prompt
  recovery) and §7.6 (paste-buffer-unsent recovery) cite this
  catalog as the source of truth for regex + keystroke.
- `agent-pane-state-patterns.md` — the broader tmux pane state regex
  catalog (idle / working / permission_prompt / stuck). This
  catalog is the permission_prompt sub-classifier.
- `fleet-communication-discipline.md` — rule #6 silent-success
  governs when the worker posts after a successful recovery.
- `fleet-close-evidence-gate.md` — if a recovery closes an issue
  (e.g. "stuck agent unblocked → close reproducer issue"), the
  worker uses the gh-issue-close-safe wrapper, not bare
  `gh issue close`.

## Incident log

Every incident that motivated a new entry or exposed a gap in
this catalog is recorded here for audit. Short, dated, with a
message ID pointer.

- **2026-04-15 msg#11799** — fleet sweep caught 5 paste-buffer-
  unsent agents. Catalog gains entry #4, paste-buffer-unsent.
- **2026-04-15 msg#11855** — head-<host> 2.5 h compound-failure
  (stale agent_meta.py + Claude Code Esc/Tab modal). Catalog
  gains entry #2, claude-esc-cancel-tab-amend. Motivates the
  fleet-health-daemon §10A probe-liveness vs agent-responsiveness
  divergence section.
- **2026-04-15 msg#11907** — worker-healer-<host> ghost-alive case
  (probe NDJSON fresh but Claude session wedged). No new catalog
  entry but confirmed the loading order above (paste-buffer
  first, then modal).
- **2026-04-14 earlier** — head-<host> concurrent-instance incident
  (scitex-orochi#144). Not a permission prompt, but informs the
  "never auto-kill duplicate Claude sessions" anti-pattern in
  the fleet-health-daemon design.
