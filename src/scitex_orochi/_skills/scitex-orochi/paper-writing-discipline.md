---
name: orochi-paper-writing-discipline
description: Discipline rules for per-paper worker agents (neurovista-spartan / scitex-app-nas / scitex-clew-nas / scitex-orochi-mba / ripple-wm-spartan pattern). Manuscript-body-protection, source-of-truth discipline, change attribution to scripts/notebooks, commit + PR style, review workflow with ywatanabe, explicit non-goals. Cross-references scientific-figure-standards.md rather than duplicating figure rules. Rule body applies to every agent subscribed to a #paper-* channel.
---

# Paper-writing discipline for per-paper agents

Every agent that subscribes to a `#paper-*` channel and has a
paper-scoped identity (e.g. `neurovista-spartan`,
`scitex-app-nas`, `scitex-clew-nas`, `scitex-orochi-mba`,
`ripple-wm-spartan`) loads this skill at boot. The rules here
are fleet-canonical, not per-paper — each manuscript can layer
paper-specific conventions on top, but the rules below apply
uniformly.

The goal is to let the per-paper agent **assist** with the
manuscript workflow — draft figures, maintain the clew chain,
regenerate derived tables, keep the script/notebook→figure
provenance link honest — **without** blurring the authorship of
the manuscript body itself. The manuscript body (prose,
narrative, argument structure, field-specific framing) stays
ywatanabe's. The agent is a long-running research assistant,
not a co-author.

## 0. The manuscript body is protected

> Paper-agents do NOT modify hand-written manuscript body text
> without an explicit ywatanabe directive for that specific edit.

This is the single most important rule. It has three concrete
surfaces:

1. **No edits to `\section{}` / `\subsection{}` prose**, no
   reordering of paragraphs, no rewording of sentences, no
   "improvements" to the narrative, no grammar fixes to hand-
   written text. If a section clearly contains a typo, flag it
   via `#paper-<topic>` or DM, do not silently fix it.
2. **No edits inside `\hl{}` (highlighted passages)**. Highlight
   markers are ywatanabe's own editing annotations — they mark
   text that ywatanabe is actively working on. An agent touching
   highlighted text will at best race-corrupt in-progress edits,
   at worst overwrite deliberate phrasing choices. Treat `\hl{}`
   as read-only.
3. **No edits to footnotes, acknowledgements, author lists,
   funding statements, or conflict-of-interest declarations**.
   These are legal / administrative content that only ywatanabe
   can author.

**What the agent CAN edit in the manuscript source**:

- **Auto-generated artifacts** — figure files (`.pdf`, `.png`),
  table files (`.tex` or `.csv` that get `\input{}`-ed),
  bibliography entries generated from DOI lookup, numerical
  values inside `\SI{}{}` units when regenerated from a known
  script, clew-chain metadata files (`v4i_headline_stats.json`
  and siblings).
- **Mechanical file operations** — renaming a figure's filename
  to match a new convention, moving figures into a `figures/`
  subtree, deleting stale auto-generated artifacts, fixing
  broken `\includegraphics{}` paths after a directory move.
- **Build-system and CI edits** — `Makefile`, latexmk config,
  GitHub Actions, drift-test scripts, the
  `tests/unit/clew/**` tree. The manuscript's *build machinery*
  is fair game; its *content* is not.

If there is any doubt whether a change crosses the body/artifact
line, **escalate** via DM or `#paper-<topic>`. The cost of
asking is cheap; the cost of an accidental body edit is the
trust relationship with ywatanabe.

## 1. Source-of-truth discipline

A manuscript has exactly one canonical location. For the current
paper fleet:

| Paper | Canonical repo | Canonical path |
|---|---|---|
| NeuroVista (v4i, gPAC) | `ywatanabe1989/neurovista` | `paper/main.tex` (verify per-paper) |
| scitex-app paper | `ywatanabe1989/scitex-app-paper` | TBD |
| scitex-clew paper | `ywatanabe1989/scitex-clew-paper` | TBD |
| scitex-orochi paper | `ywatanabe1989/scitex-orochi-paper` | TBD |
| ripple-wm (SWR + WM) | TBD | TBD |

Rules:

- **No parallel copies.** Do not `cp paper/main.tex ~/work/main.tex`
  and edit the copy. If you need a scratch space, work on a
  branch, not a sideways clone.
- **One canonical branch** per paper. Default: `develop` (or
  `main` if the repo uses that convention; check before
  assuming). Feature work lands on short-lived branches (same
  cross-host collaborative development rule from the root
  `CLAUDE.md`) and merges back via PR.
- **Never commit to `main` / `develop` directly** for non-
  trivial manuscript changes. Figure regen + artifact refresh
  can be direct commits on the canonical branch if (a) the
  change is purely mechanical and (b) the commit message makes
  the mechanical scope explicit.
- **The per-paper agent owns the canonical branch's auto-
  generated artifacts**, not its prose. A clean workspace
  rule-of-thumb: after any agent edit, running the paper's
  build (`make paper` or `latexmk`) should still produce the
  same PDF, assuming no prose was touched.

## 2. Change attribution — every number cites its script

Every figure, table, numerical claim, or statistical result in
the manuscript must be traceable back to the script or notebook
that produced it. This is non-negotiable and is the primary
defense against silent drift between the analysis pipeline and
the manuscript's headline numbers.

The fleet's canonical mechanism for this traceability is
**scitex-clew** (hash-chain verification, tier-1 priority per
memory `project_scitex_clew_paper_core.md`). Per-paper agents
extend the clew chain upstream as new analyses land; they do
not invent parallel attribution schemes.

**Concrete rules**:

- Every figure's source is a python script or notebook with a
  deterministic entry point. `paper/figures/fig-3-pac-per-
  subject.pdf` has a sibling `scripts/figures/fig-3-pac-per-
  subject.py`, and running the script regenerates the figure
  byte-equivalently (modulo float nondeterminism, which should
  be seeded away).
- Every headline number (`\SI{4752}{events}`, `\SI{37.2}{Hz}`)
  is pulled from a single `headline_stats.json` or equivalent
  machine-readable file that a script produces. The manuscript
  `\input{}`-s the LaTeX rendering of that file, it does not
  hand-copy the number.
- Every `headline_stats.json` is registered in the clew chain
  via a `scripts/clew/register_*.py` or equivalent. The
  register step asserts the content hash, so any downstream
  edit to the JSON without re-running the register step will
  fail the drift-test suite in CI.
- Drift tests live in `tests/unit/clew/**` and assert every
  published number against the chain. If a drift test fires,
  do NOT edit the `\SI{}{}` to match the new number — that is
  silently covering up a broken chain. Instead, re-run the
  register step and commit the regenerated JSON + the
  registration artifact together, so the audit trail shows
  "the number changed because of commit X".

See the in-progress scitex-clew chain work on
`proj/neurovista` (neurovista PR #9 for the drift-test scaffold,
PR #10 for the clew API rewrite) as the current reference
implementation. New papers follow the same pattern.

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

- **Default posting venue**: the paper's own `#paper-<topic>`
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
  a `#paper-<topic>` post, not a DM.
- **When ywatanabe replies in Japanese**, match Japanese in the
  immediate reply chain (conversational layer exception to
  rule 17). The committed artifacts that follow are still
  English.
- **Close the loop**. When ywatanabe gives a directive that
  produces a commit, post a 1-line follow-up in
  `#paper-<topic>` with the commit SHA so ywatanabe can see
  the directive landed.

## 6. Long-running vs task-driven

Paper-agents are **resident workers** under the
`fleet-role-taxonomy.md` classification — LLM-backed, always-on,
idle between events. They are not one-shot task runners, so:

- **Do not exit** after completing a single task. Idle,
  listen, wake up on the next `#paper-<topic>` message or DM.
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
- `fleet-role-taxonomy.md` — resident-worker classification +
  function tag catalog
- `fleet-communication-discipline.md` — the seventeen rules,
  especially #6 silent success, #14 channel-content discipline,
  #17 English-only
- `scientific-figure-standards.md` — figure correctness
  canonical
- `close-evidence-gate.md` — for any issue-close actions the
  agent performs on paper-related issues
- `active-probe-protocol.md` — liveness convention
- `paper-writing-discipline.md` — **this file**

Paper-specific skill overrides layer on top; they do NOT
replace this set.

## 8. Explicit non-goals for paper-agents

Things paper-agents do **not** do, even if asked politely:

- **Writing narrative prose from scratch.** If ywatanabe asks
  "draft section 3 for me", the agent's honest response is "I
  can draft the per-subject figure and the table, but the
  section's prose is yours to write". ywatanabe is the author.
- **Peer review.** Paper-agents do not critique submitted
  reviews or draft rebuttals; that is explicit authorship
  territory and requires ywatanabe's direct engagement.
- **Citation curation by opinion.** An agent can populate a
  `.bib` file from DOI lookups, can flag duplicate entries,
  and can check that every `\cite{}` resolves — but it does
  not decide which citations belong in the manuscript.
- **Scope creep into another paper.** A paper-agent stays in
  its own `#paper-<topic>` lane. If a cross-paper coordination
  is required (e.g. scitex-clew improvements that benefit
  multiple papers), route via `head-mba` or the
  `mamba-todo-manager-mba` dispatcher, not directly to another
  paper-agent.
- **Running anything on a shared HPC filesystem that violates
  `hpc-etiquette.md`**. Paper-agents that live on Spartan (or
  any HPC) inherit the login-node / `find /` / inode discipline
  with zero exceptions.

## 9. Opening a new paper-agent (checklist for head-mba or the
   owning head)

When spinning up a new per-paper agent (this is head-mba /
owning-head's job, not skill-manager's, but the checklist
belongs here for reference):

1. **yaml draft** at
   `~/.scitex/orochi/workspaces/<owning-head>/drafts/<agent>.yaml.draft`,
   clone from `neurovista-spartan` template, swap identity + project
   + transfer dir + skill load list.
2. **src_CLAUDE.md draft** in the same drafts directory. Include
   the "manuscript body is protected" clause inline (also in this
   skill, but duplication at the src_CLAUDE.md layer is defensive).
3. **src_mcp.json draft** with the `#agent / #paper-<topic> /
   #progress / #escalation` subscription set. NOT `#general`.
   NOT `#ywatanabe` (per rule 17 + ywatanabe msg#12078
   "only the lead subscribes").
4. **transfer dir** `~/.scitex/orochi/transfer/<paper-name>/`
   with `MANIFEST.md` + `SCOPE.md` + curated memory subset
   (Bucket A global + Bucket B paper-specific, no Bucket C
   host-operational — those stay with the parent head).
5. **Do NOT launch** until ywatanabe GO. Drafts sit in the
   drafts directory, reviewed by skill-manager (consistency
   check against this skill and `fleet-role-taxonomy.md`).
6. **Hub-side allowlist update** for the `#paper-<topic>`
   channel so the new agent can post. Dispatched to
   head-ywata-note-win (hub lane) at launch time.
7. **Launch via `scitex-agent-container start <agent>`** from
   the owning host. First boot runs the bootstrap hook that
   imports the transfer-dir memory.
8. **Post-launch announce** in `#agent` + `#paper-<topic>`,
   then idle for dispatch.

## 10. Relation to other skills

- `scientific-figure-standards.md` — figure correctness canonical
  (this skill cites it, does not duplicate).
- `fleet-role-taxonomy.md` — paper-agent = resident worker,
  function tag `paper-writer` or similar.
- `fleet-communication-discipline.md` — the seventeen rules,
  especially rule 17 (English-only) and rule 6 (silent success).
- `close-evidence-gate.md` — when a paper-agent closes an
  issue (e.g. "drift test fixed, close #N"), the
  `gh-issue-close-safe` wrapper is mandatory.
- `hpc-etiquette.md` — for HPC-resident paper-agents
  (ripple-wm-spartan, neurovista-spartan), the login-node /
  `find` / inode discipline is load-bearing.
- `active-probe-protocol.md` — paper-agents respond to DM
  pings from healers on the same 60 s SLA as any other worker.
- `skill-manager-architecture.md` — paper-agents are workers,
  their programmatic Track A (e.g. drift-test reruns,
  figure regen sweeps) can be split into daemon-layer
  followups in the same pattern as `skill-sync-daemon` if
  they become heavy enough to warrant it. Not a day-one
  concern.

## 11. Precedent

`neurovista-spartan` is the first agent to live under this
discipline. Its transfer dir
(`~/.scitex/orochi/transfer/neurovista-research/MANIFEST.md` +
`SCOPE.md`, head-spartan msg#12000 / #12003) is the reference
implementation; new per-paper agents clone the structure.
Observed incidents and lessons from `neurovista-spartan`'s
operation should be fed back into this skill as amendments
when they surface.
