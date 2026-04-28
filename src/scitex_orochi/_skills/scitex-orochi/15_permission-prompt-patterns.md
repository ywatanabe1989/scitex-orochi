---
name: orochi-permission-prompt-patterns
description: Canonical pattern catalog for Claude Code permission prompts and other interactive "agent is stuck waiting for a keystroke" states. Loaded at boot by mamba-healer-<host> workers so the fleet-health-daemon Phase 4 recovery playbook §7.1 has concrete regex → action mappings. Grows by observation per ywatanabe msg#11779 ("パターンを蓄積することが大事"). Not executed by humans — fed to automation.
---

# Permission-Prompt Patterns

When a Claude Code pane is blocked on a permission / confirmation /
selection prompt, the worker-layer healer needs a concrete answer
to two questions, fast:

1. **Is this actually a permission prompt, or just something that
   looks like one** (e.g. a legitimate multi-choice prompt the
   agent is composing, or a selection menu mid-interactive
   command)?
2. **If yes, which keystroke unblocks it without lying about
   consent** (i.e. which option is the "go ahead, but respect
   existing allowlists" choice)?

This skill is the catalog of known prompts, their exact regexes,
and the recovery keystroke for each. Workers read it at boot and
attach it to `fleet-health-daemon-design.md` §7.1 (permission-
prompt recovery) as the lookup table. **The catalog is not
exhaustive.** It grows every time the fleet observes a new
prompt pattern. Treat every new observation as a commit
candidate.

## Why a catalog, not a catch-all

ywatanabe msg#11779 is explicit: "パターンを蓄積することが大事" —
pattern accumulation is the important discipline, not a greedy
"auto-send Enter on anything that looks stuck" heuristic. A
greedy heuristic race-corrupts agents mid-composition (see
`fleet-health-daemon-design.md` §7.6, head-mba MBA sweep
2026-04-15 caught paste-buffer-unsent cases where a blanket-Enter
would have submitted garbage). A curated catalog with explicit
regex + action + rationale is the inverse: slow to add a new
pattern but always safe per pattern.

## Entry schema

Every entry in this catalog has the same 7 fields:

```
- id:               short stable slug
  regex:            Python regex that matches the prompt text within a tmux capture
  observed-as:      human-readable description of what a human would see on screen
  first-seen:       date + message ID where the pattern was first observed
  recovery-keystroke: the tmux send-keys sequence, as a string
  rationale:        why this keystroke is the right answer (which option it selects)
  escalation:       when to stop retrying and post to #escalation
```

## Continued in

- [`62_permission-prompt-patterns-extras.md`](62_permission-prompt-patterns-extras.md)
