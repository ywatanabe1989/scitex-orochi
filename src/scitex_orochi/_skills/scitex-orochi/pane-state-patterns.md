---
name: orochi-pane-state-patterns
description: Canonical regex catalog for classifying tmux pane state of an Orochi Claude Code agent. Feeds into auto-unblock + credential rotation + "working side" triage. Upstream truth at ~/.emacs.d/lisp/emacs-claude-code.
---

# Pane State Patterns

Every fleet healer, watchdog, and auto-unblock loop needs one shared way to answer "what is this tmux pane doing right now?" This skill is the canonical regex catalog. It is a **library**, not a process — `scitex-orochi/pane_state.py` (PR #118) and future healer loops consume it.

## Why

2026-04-13 the fleet hit every failure mode in a single session: dev-channels prompts that blocked for 5 hours, quota exhaustion banners that looked like idle cursors, permission prompts that nobody answered, `--continue` conflicts manifesting as startup hangs, mcp-channel zombies that left the pane silent, and a classifier that mistook "busy" for "dead" because it only looked at Orochi post timestamps.

ywatanabe's directive was consistent (msgs #9438 / #9442 / #9550 / #9674 / #10210):

1. Collect the patterns, don't invent them on each observation.
2. Classify by state, not by guess.
3. **Fall to the working side** — auto-answer benign prompts, default to continuing, escalate only when unsafe.
4. Single source of truth: `~/.emacs.d/lisp/emacs-claude-code` has already catalogued the patterns — mirror, don't diverge.

## States

A pane is in **exactly one** of the states below per classification call:

| State | Meaning | Severity | Auto-action |
|---|---|---|---|
| `:running` | Claude is actively producing tokens | green | none |
| `:waiting` | Claude at `❯` prompt, no queue, alive | green | none |
| `:mulling` | Claude animation active (`* Mulling…` / `* Pondering…` / `* Churning…` / `Roosting…`) | green | none — busy, not idle |
| `:paste_pending` | `Press up to edit queued messages` or similar; input already queued | green | send `Enter` once |
| `:permission_prompt` | Generic "Do you want to proceed? (y/n)" or numbered choices | yellow | send the **safe** option (`2`/`n`) by default |
| `:dev_channels_prompt` | First-run "I am using this for local development" 1/2 prompt | yellow | send `1` Enter (dev acceptance) |
| `:auth_needed` | `/login` flow, OAuth URL visible, awaiting code paste | yellow | post URL to `#ywatanabe`, wait for code |
| `:quota_exhausted` | "out of extra usage · resets …" | red | swap credential per `agent-account-switch.md` |
| `:quota_warning` | `\d\d% \| Limit reach` (≥ 80%) | yellow | pre-emptive swap if alternate account < 70% |
| `:mcp_broken` | `.mcp.json` missing or sidecar died; hub heartbeat stopped while pane looks fine | red | `scitex-agent-container restart` |
| `:stuck_error` | API error messages not matching quota/auth patterns | red | capture pane, escalate to `#escalation` |
| `:dead` | Claude exited; pane shows shell prompt or empty | red | autostart unit should respawn; else escalate |
| `:unknown` | Nothing matched | neutral | log + alert, never guess |

**`:running` and `:mulling` are not idle.** Healers that escalate on "silent for N seconds" without checking the animation row produce false positives. This was the 2026-04-13 head-spartan incident.

## Regexes

Match on the **tail** of `tmux capture-pane -pt "${PANE}"` (last 60–200 lines). Regexes are case-sensitive unless noted.

### `:mulling` — busy animation
```
(?m)^\s*[*✻]\s*(Mulling|Pondering|Churning|Roosting|Thinking|Cogitating|Musing|Reflecting)…?\s+\(\d+\w+
```
Notes: Claude's animation verbs rotate. `emacs-claude-code` upstream has the full list — mirror from there, don't invent.

### `:paste_pending`
```
Press up to edit queued messages
```
Singular match, bottom of pane. Trigger: send `Enter` once, then re-capture.

### `:permission_prompt` — generic y/n
```
(?mi)(Do you want to proceed\?|\[y/N\]|\(y/n\)|Continue\?)
```
Action: the **safe default** varies per prompt. Healer must also match the prompt *context*:

- File-edit prompts → default `y` if the file is under `~/.scitex/` / `~/proj/`, else `n`
- Network install prompts (`pip install`, `apt install`) → `n` by default unless agent context authorizes
- Unknown → `n` and escalate

### `:permission_prompt` — numbered 1/2/3
```
(?m)^\s*❯?\s*(1\.|2\.|3\.)\s+[A-Z]
```
Action: pair with context. Commonly `2` = safe "exit / cancel", `1` = "proceed in dev mode". The dev-channels prompt below is a specific subtype.

### `:dev_channels_prompt` — first-run dev channels
```
I am using this for local development
```
Full prompt (from the 2026-04-13 head-spartan incident):
```
❯ 1. I am using this for local development
  2. Exit
```
Action: send `1` + Enter (accept dev mode). See memory `project_permission_prompt_blockers.md` — `--dangerously-skip-permissions` does not cover this one.

### `:auth_needed` — OAuth login
```
https://claude\.com/cai/oauth/authorize\?code=true
```
Or:
```
(?i)Paste your login code here
```
Action: extract the URL, post to `#ywatanabe` (as file or chat), wait for the code. Do not attempt to auto-complete OAuth — the code comes from the human.

### `:quota_exhausted`
```
(?i)out of extra usage
```
Or:
```
(?i)resets (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d+
```
Or:
```
/extra-usage to finish what you're working on
```
Action: trigger `agent-account-switch.md` swap.

### `:quota_warning`
```
(?m)(8\d|9\d)%\s+⚠\s+Limit reach
```
Action: pre-emptive swap if the alternate account is < 70% on both windows.

### `:mcp_broken`
Pane looks fine but:

- `pgrep -f 'bun.*mcp_channel' -c` returns 0 on the host for this agent **and**
- hub `/api/agents/<agent>/` shows `last_heartbeat` older than 3 × sampler period

Action: `scitex-agent-container restart <yaml>` — side-car-only restart, preserves Claude Code state. Escalate if restart fails twice in 10 minutes.

### `:stuck_error`
Generic fallback for API errors not matching the quota/auth patterns:
```
(?i)(API Error|internal server error|rate.?limit|ECONNRESET|unexpected EOF)
```
Do not auto-retry — capture pane, post to `#escalation`, let a human route.

### `:dead`
```
(?m)^\s*\$\s*$
```
Or `tmux capture-pane` returns empty. Claude exited, shell prompt or blank. Action: autostart unit should respawn; if autostart fails, escalate.

## Classification algorithm

Priority order (highest wins — exit on first match):

1. `:mulling` — animation active → busy
2. `:paste_pending`
3. `:auth_needed`
4. `:quota_exhausted`
5. `:dev_channels_prompt`
6. `:permission_prompt` (numbered, then y/n)
7. `:quota_warning`
8. `:stuck_error`
9. `:mcp_broken` — requires external heartbeat check
10. `:dead` — requires shell-prompt match
11. `:running` — if active output seen in the last 5 seconds
12. `:waiting` — default when nothing above matches and pane tail ends with `❯`
13. `:unknown` — any other case

## Auto-actions

Healers call this module read-only to **classify**, then consult a per-state action table before acting. Action table is **per-agent** (healers may disable auto-unblock on production agents) and **per-host** (spartan must not `systemctl --user restart` anything).

| State | Default action | Confirmation needed? |
|---|---|---|
| `:mulling` | none | no |
| `:paste_pending` | `Enter` | no |
| `:permission_prompt` (safe) | `n` / `2` | no |
| `:dev_channels_prompt` | `1` + Enter | no |
| `:auth_needed` | post URL to `#ywatanabe` | no |
| `:quota_exhausted` | credential swap | no, if alternate < 70% |
| `:quota_warning` | pre-swap | yes (log warn first) |
| `:mcp_broken` | `scitex-agent-container restart` | yes, escalate if repeated |
| `:stuck_error` | post to `#escalation` | no (informational) |
| `:dead` | autostart unit | no |
| `:unknown` | escalate once, do not act | no |

## Upstream: `~/.emacs.d/lisp/emacs-claude-code`

This catalog mirrors `~/.emacs.d/lisp/emacs-claude-code` (GitHub: `ywatanabe1989/emacs-claude-code`). When a new Claude Code prompt / animation is observed, update that repo first and sync the regex here. Single source of truth.

**Do not fork and drift.** If this file and the emacs package disagree, the emacs package wins and this skill gets a PR.

## Consumers in the fleet

- `scitex-orochi/scripts/pane_state.py` (PR #118) — Python implementation reading the catalog.
- `scripts/fleet-watch/fleet-prompt-actuator` (head-nas, running on NAS cron) — auto-unblock healer loop.
- `mamba-healer-*` `/loop` prompts — future adoption layer, codifies per-host action tables.
- `pane_state` field in hub `/api/agents/` — planned surface for the Agents tab (PR series TBD).

## What this skill does NOT cover

- It does **not** decide *when* to run the classifier (that's the healer / watchdog).
- It does **not** ship an implementation; it is the spec that implementations mirror.
- It does **not** cover Claude Code *session* state (context %, token count). That's `context_percent` in `status --json`, not pane scraping.

## Related

- `agent-account-switch.md` — the action taken on `:quota_exhausted` / `:quota_warning`
- `agent-health-check.md` — the 8-step health checklist that calls this classifier
- `connectivity-probe.md` — how to distinguish remote pane state safely
- `fleet-communication-discipline.md` rule #6 — silent success
- memory `project_permission_prompt_blockers.md` — why `--dangerously-skip-permissions` is insufficient
- Upstream: `~/.emacs.d/lisp/emacs-claude-code` (single source of truth for Claude pane regex)
- head-nas PR #118 — Python reference implementation

## Change log

- **2026-04-14 (initial)**: Drafted from 2026-04-13 fleet pattern observations (msgs #8670 / #9438 / #9442 / #9537 / #9670 / #9674 / #10210 / #10216). States, regexes, priority order, and action table consolidated from head-nas PR #118 + emacs-claude-code upstream. Author: mamba-skill-manager.
