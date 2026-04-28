---
name: orochi-agent-pane-state-patterns-consumers
description: Upstream single-source-of-truth memory + fleet consumers + scope/exclusions + change log. (Split from 57_agent-pane-state-patterns-extras.md.)
---

> Sibling: [`74_agent-pane-state-patterns-detection.md`](74_agent-pane-state-patterns-detection.md) for detection algorithm + auto-actions.

## Upstream single source of truth (memory: `project_tui_pattern_single_source`)

This skill is a **mirror**, not a primary. Three sibling catalogs hold the authoritative regex for pane state, and they are kept in sync by humans + worker-skill-manager, **not** by agents inventing new patterns in this file:

| Source | Location | Role |
|---|---|---|
| **Elisp (upstream)** | `~/.emacs.d/lisp/emacs-claude-code/ecc-state-detection.el` (GitHub `the operator1989/emacs-claude-code`) | the operator's primary TUI observation point. New patterns are observed in Emacs first. |
| **Python (runtime)** | `scitex-agent-container/src/scitex_agent_container/runtimes/prompts.py` | Used by `scitex-agent-container` watchdog / healer code paths at runtime. |
| **Markdown (this skill)** | `scitex-orochi/_skills/scitex-orochi/agent-pane-state-patterns.md` | Human-readable catalog that fleet healers, skill writers, and documentation reference when explaining behavior. |

### Sync protocol

When a new Claude Code pane pattern is discovered:

1. **Elisp first.** Add the regex + matcher in `ecc-state-detection.el` during live Emacs observation. This is the place it is first seen, and `emacs-claude-code` has the shortest feedback loop (interactive eval, live buffer).
2. **Python next.** Port the regex verbatim into `prompts.py`, keeping variable names and matcher semantics aligned. Add a unit test that exercises the new pattern with a captured pane example.
3. **Markdown last.** Update this skill to reflect the new state. The skill update is always **post-hoc** relative to the Elisp + Python changes — never introduce a state here that does not yet exist upstream.
4. Commit the three changes with a single rationale in the commit messages, cross-referencing each other and the source msg id where the pattern was observed.

### Drift policy

- **If Elisp and Python disagree**, Elisp wins. File a Python PR to align.
- **If Python and this skill disagree**, Python wins. Update this skill.
- **If this skill adds a state that neither Elisp nor Python has**, **revert the skill change and file a PR against Elisp first**. Skill-only states are documentation fiction and must not ship.
- **Do not fork the regex string.** If a new state's regex needs to vary slightly per upstream (e.g., Emacs handles newlines differently from bash capture-pane), encode the variation in the matcher logic of each language, not by shipping two different regexes.

This mirror discipline is memory rule `project_tui_pattern_single_source`: **the Elisp repo is the canonical observation point, Python is the runtime consumer, Markdown is the documentation mirror**. Agents asking "can I add a new state directly here" should be told **no** — start in Emacs.

See also: head-<host> PR #118 (`pane_state.py` reference implementation — may be a fourth alias once landed; same rules apply).

## Consumers in the fleet

- `scitex-orochi/scripts/pane_state.py` (PR #118) — Python implementation reading the catalog.
- `scripts/fleet-watch/fleet-prompt-actuator` (head-<host>, running via cron on the storage host) — auto-unblock healer loop.
- `worker-healer-*` `/loop` prompts — future adoption layer, codifies per-host action tables.
- `pane_state` field in hub `/api/agents/` — planned surface for the Agents tab (PR series TBD).

## What this skill does NOT cover

- It does **not** decide *when* to run the classifier (that's the healer / watchdog).
- It does **not** ship an implementation; it is the spec that implementations mirror.
- It does **not** cover Claude Code *session* state (context %, token count). That's `context_percent` in `status --json`, not pane scraping.

## Related

- `agent-account-switch.md` — the action taken on `:quota_exhausted` / `:quota_warning`
- `agent-health-check.md` — the 8-step health checklist that calls this classifier
- `convention-connectivity-probe.md` — how to distinguish remote pane state safely
- `fleet-communication-discipline.md` rule #6 — silent success
- memory `project_permission_prompt_blockers.md` — why `--dangerously-skip-permissions` is insufficient
- Upstream: `~/.emacs.d/lisp/emacs-claude-code` (single source of truth for Claude pane regex)
- head-<host> PR #118 — Python reference implementation

## Change log

- **2026-04-14 (initial)**: Drafted from 2026-04-13 fleet pattern observations (msgs #8670 / #9438 / #9442 / #9537 / #9670 / #9674 / #10210 / #10216). States, regexes, priority order, and action table consolidated from head-<host> PR #118 + emacs-claude-code upstream. Author: worker-skill-manager.
