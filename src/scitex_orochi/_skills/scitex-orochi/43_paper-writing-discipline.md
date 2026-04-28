---
name: orochi-paper-writing-discipline
description: Discipline rules for per-paper worker agents (proj-scitex-app-nas / proj-scitex-clew-nas / proj-scitex-orochi-mba / proj-ripple-wm-spartan / neurovista-spartan pattern). Manuscript-body-protection, source-of-truth discipline, change attribution to scripts/notebooks, commit + PR style, review workflow with ywatanabe, narrow-subscription trade-offs, explicit non-goals. Cross-references scientific-figure-standards.md rather than duplicating figure rules. Rule body applies to every agent subscribed to a #proj-* channel.
---

# Paper-writing discipline for per-paper agents

Every agent that subscribes to a `#proj-*` channel and has a
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
   via `#proj-<topic>` or DM, do not silently fix it.
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
line, **escalate** via DM or `#proj-<topic>`. The cost of
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

## Continued in

- [`46_paper-writing-discipline-process.md`](46_paper-writing-discipline-process.md)
- [`47_paper-writing-discipline-checklists.md`](47_paper-writing-discipline-checklists.md)
