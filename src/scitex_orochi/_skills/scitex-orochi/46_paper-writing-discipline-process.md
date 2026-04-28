---
name: orochi-paper-writing-discipline-part-2
description: Discipline rules for per-paper worker agents (proj-scitex-app-nas / proj-scitex-clew-nas / proj-scitex-orochi-mba / proj-ripple-wm-spartan / neurovista-spartan pattern). Manuscript-body-protection, source-of-truth discipline, change attribution to scripts/notebooks, commit + PR style, review workflow with ywatanabe, narrow-subscription trade-offs, explicit non-goals. Cross-references scientific-figure-standards.md rather than duplicating figure rules. Rule body applies to every agent subscribed to a #proj-* channel. (Part 2 of 3 — split from 43_paper-writing-discipline.md.)
---

> Part 2 of 3. See [`43_paper-writing-discipline.md`](43_paper-writing-discipline.md) for the orchestrator/overview.
## 3. Figure discipline — cross-reference, do not duplicate

Figure correctness is canonical in `scientific-figure-standards.md`.
Paper-agents load **both** skills at boot; do not duplicate that
content here. Key rules from that skill that paper-agents must
follow without exception:

- Sample size disclosed on every figure.
- `H₀` mandatory; `H₁` disclosed when defined.
- Shaded mean ± SD per subject, aligned time windows.
- Event annotations (red vertical line at `t=0` for the event
  of interest).
- Per-subject figures + grand-summary figure — the pair is the
  unit, not either alone.
- FDR-floor null-control for every statistical claim.

Paper-agents authoring figure scripts default to the
`scitex.plt` + `scitex.stats` surfaces the standards skill
recommends. When those surfaces are missing a feature, the
escalation is to open an issue against scitex-core, not to
hand-roll a competing plotting helper in the paper repo.

## 4. Commit discipline — English, rule 17

All commit messages, PR titles, PR bodies, and issue comments
produced by paper-agents are in English (rule 17,
`fleet-communication-discipline.md`). Japanese discussion
happens only in the conversational layer (DMs, `#ywatanabe`
posts when ywatanabe is using Japanese).

Commit style for manuscript-adjacent changes:

- **Subject line under 70 chars**, scope prefix
  (`docs(paper)`, `figs(paper)`, `tests(clew)`, `ci(paper)`,
  etc.). The subject should name the specific figure / table /
  test that changed.
- **Body** explains the *why*, not the *what*. "Regenerated
  figure 3 after rerun of `scripts/figures/fig3.py`" is a
  what; "figure 3 regenerated because pac window width was
  corrected from 4s to 5s per ywatanabe email 2026-04-10" is
  a why.
- **Reference the paper-channel message ID** or the driving
  issue in the commit trailer so the audit trail links back
  to the reasoning.
- **No co-authorship trailers for ywatanabe**. ywatanabe is
  the author of the manuscript body; the agent is the author
  of the artifacts. Conflating the two muddies the authorship
  audit.

## 5. Review workflow with ywatanabe

Per-paper agents are long-running and should minimize the
number of times they interrupt ywatanabe.

- **Default posting venue**: the paper's own `#proj-<topic>`
  channel. That's what the channel is for.
- **`#ywatanabe` is for cross-paper or fleet-level questions**,
  not per-paper progress. Do not relay per-paper progress into
  `#ywatanabe` unless ywatanabe asked.
- **DM ywatanabe** for decisions that require a judgment call
  the agent cannot make from the available context (e.g.
  "which of these two analysis pipelines should we keep",
  "is this figure worth publishing"). DMs are higher-friction
  than channel posts; reserve them for actual decisions.
- **Do not DM for routine progress updates**. If the update
  is "finished running the drift tests, 11/11 pass", that's
  a `#proj-<topic>` post, not a DM.
- **When ywatanabe replies in Japanese**, match Japanese in the
  immediate reply chain (conversational layer exception to
  rule 17). The committed artifacts that follow are still
  English.
- **Close the loop**. When ywatanabe gives a directive that
  produces a commit, post a 1-line follow-up in
  `#proj-<topic>` with the commit SHA so ywatanabe can see
  the directive landed.

## 6. Long-running vs task-driven

Paper-agents are **resident workers** under the
`fleet-role-taxonomy.md` classification — LLM-backed, always-on,
idle between events. They are not one-shot task runners, so:

- **Do not exit** after completing a single task. Idle,
  listen, wake up on the next `#proj-<topic>` message or DM.
- **Do log silently** during idle. Don't post "still alive"
  heartbeats; the fleet-health-daemon covers liveness.
- **Do track outstanding follow-ups** in a local workspace
  note (`~/.scitex/orochi/workspaces/<agent>/followups.md`) so
  the agent remembers what it owed ywatanabe across reboots.
- **Do not take on work outside the paper's scope** unless
  explicitly dispatched by `head-mba` or ywatanabe. Cross-paper
  helping is fine when asked, but unsolicited scope creep is
  a coordination hazard.

## 7. Skill inheritance for new paper-agents

Every per-paper agent loads the following skills at boot
(in addition to this one):

- `scitex-orochi` (root fleet skill)
- `scitex-agent-container` (root container skill)
- `paper-writing-discipline` — **this file** (one of the sub-
  skills inside the `scitex-orochi` bundle above)

**Important clarification on the skill loader**: the first two
entries (`scitex-orochi` and `scitex-agent-container`) are the
only **top-level loadable skill bundles** that an agent's
yaml `spec.skills.required` block should list. Each bundle is
a directory containing many sub-file skills — for the
`scitex-orochi` bundle these include but are not limited to:

| Sub-file | Purpose for paper-agents |
|---|---|
| `fleet-role-taxonomy.md` | Resident-worker classification + function tag catalog |
| `fleet-communication-discipline.md` | Seventeen rules, especially #6 silent success, #14 channel-content, #17 English-only |
| `scientific-figure-standards.md` | Figure correctness canonical — sample size, H₀/H₁, shaded mean±SD, event annotations |
| `close-evidence-gate.md` | Issue-close wrapper for paper-related issue management |
| `active-probe-protocol.md` | Liveness convention for DM pings |
| `paper-writing-discipline.md` | This file |
| `hpc-etiquette.md` | For HPC-resident paper-agents (Spartan, future NCI, etc.) |

The sub-file names above are **descriptive, not loadable**.
Listing a sub-file name in `spec.skills.required` either
duplicates what the bundle already loads (harmless no-op) or
fails the parser if the bundle loader treats sub-file entries
as missing bundles. Prefer the top-level bundle names only
(`scitex-orochi`, `scitex-agent-container`, plus
`scitex` / `scitex-clew` when those bundles are in use)
and trust the bundle to load all relevant sub-files at boot.

Paper-specific skill overrides layer on top; they do NOT
replace this set.
