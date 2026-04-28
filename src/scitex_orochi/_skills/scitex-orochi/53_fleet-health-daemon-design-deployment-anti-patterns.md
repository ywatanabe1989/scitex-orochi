---
name: orochi-fleet-health-daemon-deployment-anti-patterns
description: §11–§14 — anti-patterns, open questions, implementation order, related skills. (Split from 53_fleet-health-daemon-design-deployment-ops.md.)
---

> Sibling: [`72_fleet-health-daemon-design-deployment-divergence.md`](72_fleet-health-daemon-design-deployment-divergence.md) for the probe-liveness vs agent-responsiveness divergence.

## 11. Anti-patterns

1. **"fleet-health-daemon is one agent"** — no. 2-layer stack.
2. **"daemon injects keystrokes"** — never. Judgment is worker-side.
3. **"worker polls instead of reading breadcrumbs"** — defeats the
   quota relief. Worker idles between breadcrumb events.
4. **"continuous threshold chatter to `#heads`"** — daemons are
   silent-otherwise. (`#agent` was abolished 2026-04-21; cross-head
   chatter now lives in `#heads`, lead-moderated.)
5. **"one healer on NAS covers everything"** — violates host
   diversity and the redundancy-mesh requirement.
6. **"reshape NDJSON schema when adding a signal"** — append only.
7. **"auto-kill duplicate Claude sessions"** — legitimate
   concurrent conversations exist (head-spartan msg#11708,
   formalised as scitex-orochi#144). Escalate, do not act.
8. **"daemon does unbounded `find`"** — violates
   `hpc-etiquette.md`.
9. **"Phase 2 signals before Phase 1 quota is shipping"** —
   do not yak-shave the broader probe before the quota
   collector is live. ywatanabe msg#11775 is explicit.
10. **"per-agent quota ceilings hardcoded in the daemon"** —
    wrong layer. Daemon emits raw counts; limits are either
    fetched by the worker from the Anthropic API and cached to a
    shared file, or loaded from a skill-manager-curated
    `quota-limits.md`. Don't bake Anthropic's pricing into the
    daemon binary.

## 12. Open questions / future work

1. **Schema versioning.** `probe_version` field hook present; a
   concrete SemVer policy (major = breaking, minor = append-only
   field, patch = bug fix) is TBD.
2. **Hub aggregation endpoints.** `/api/fleet/quota/` is Phase 1.
   `/api/fleet/health/` for the full multi-signal vector lands in
   Phase 2, owned by head-ywata-note-win, tracked under
   `scitex-orochi#155` observability epic.
3. **Dashboard integration.** Per-agent quota bars (5h + weekly)
   in the `Agents` tab land in Phase 1. Per-host health scores
   land in Phase 2.
4. **Recovery action audit log.** Worker writes
   `<breadcrumb>.handled` files per recovery; weekly rollup
   deferred until the base daemon is in production.
5. **Absolute quota limits.** Phase 1b — either Anthropic API or
   known-constant fallback via `quota-limits.md`. Not a Phase 1
   blocker.
6. **Permission-prompt patterns catalog.** Growing
   `permission-prompt-patterns.md` skill doc, loaded at worker
   boot, updated when new prompts are observed. Pattern
   accumulation is continuous per ywatanabe msg#11779.

## 13. Implementation order

Phase 1 is the immediate deliverable; Phase 2+ are follow-ups
landing as separate PRs.

**Phase 0** (this PR): design doc published, naming locked, 2-layer
taxonomy ratified, Spartan constraint matrix integrated.

**Phase 1** (immediate follow-up, separate implementation PR):
1. Extend `mamba-healer-nas`'s existing probe script (msg#11567,
   #11709, #11730, #11746, #11750, #11788) to:
   - scrape `~/.claude/projects/<ws>/*.jsonl` for the quota fields
   - parse `~/.claude/config.json` + `settings.json`
   - read `agent_meta.py` statusline output for `context_pct`
   - emit the Phase 1 quota NDJSON fields alongside the existing
     Phase 2 signals (append-only)
2. Port the probe to MBA as `fleet-health-daemon` via launchd;
   same entrypoint, plist wrapper. Runs alongside NAS, cross-
   merged on `ts` for validation.
3. Port to WSL (systemd --user, same unit as NAS).
4. Port to Spartan (tmux loop wrapper, Lmod `Python/3.11.3` init
   per PR #141 + §8.1 Spartan matrix).
5. Hub `/api/fleet/quota/` endpoint (head-ywata-note-win,
   coordinated with `/api/agents/` extension in the #132 / #155
   lane).
6. Dashboard `Agents` tab quota bars (head-ywata-note-win).
7. Close `scitex-orochi#272` / `scitex-orochi#430` with
   "resolved by fleet-health-daemon Phase 1, see PR" comments.

**Phase 2** (follow-up): full multi-signal probe
(docker stats, cpu.pressure, systemd units, MCP dedup, pane
state). Everything in §5.

**Phase 3** (follow-up): worker-side consumer — extend
`mamba-healer-mba` / `mamba-healer-nas` / new
`mamba-healer-spartan` / `mamba-healer-ywata-note-win` to read
daemon NDJSON + breadcrumbs, cross-probe peers, own the recovery
playbook.

**Phase 4** (follow-up): recovery action playbook (§7) — executable
automation, not catalog docs. Systematic resurrection +
periodic 5-min sweep.

**Phase 1b** (parallel): absolute quota limits via Anthropic API
or known-constant fallback.

## 14. Related skills / issues

- `fleet-role-taxonomy.md` — 2-layer + role × function model.
- `skill-manager-architecture.md` — first pilot of the same
  daemon/worker split; fleet-health-daemon is the second.
- `slurm-resource-scraper-contract.md` — external-tool-compat
  design principle (stock CLI output as wire format) that
  Phase 1 follows for Claude Code JSONL + statusline.
- `active-probe-protocol.md` — DM-ping probe for cross-host
  mutual probing in Phase 3.
- `random-nonce-ping-protocol.md` — 60 s liveness check that
  stays orthogonal to the 30 s daemon tick.
- `agent-autostart.md` — Spartan Lmod `Python/3.11.3` wrapper
  (PR #141) that Phase 1 inherits.
- `pane-state-patterns.md` — canonical regex catalog for the
  `pane_states` signal (Phase 2).
- `fleet-communication-discipline.md` — silent-otherwise rule
  #6 that the daemon obeys.
- `hpc-etiquette.md` — login-node / `find` / `du` discipline on
  Spartan.
- `close-evidence-gate.md` — `gh-issue-close-safe` wrapper the
  worker uses when closing an issue as part of a recovery.
- **Issues this design subsumes**:
  - `ywatanabe1989/todo#146` — parent, this design doc is its
    spec.
  - `scitex-orochi#272` — proactive quota pressure detection
    (Phase 1 deliverable).
  - `scitex-orochi#430` — per-agent Claude API quota telemetry
    (Phase 1 deliverable, dup of #272, one of them closes at
    Phase 1 merge).
  - `ywatanabe1989/todo#142` — Agents-stuck permission prompts
    (Phase 4 recovery playbook §7.1 + §7.6 periodic sweep).
  - `scitex-orochi#144` — concurrent Claude instance race hazard
    (Phase 2 anti-pattern §11 #7).

---

**Ground-truth sources consulted during drafting** (msg IDs
approximate per `fleet-role-taxonomy.md` convention):

- mamba-healer-nas probe data + JSONL feasibility — msg#11536,
  #11540, #11567, #11709, #11730, #11746, #11750, #11788
- mamba-explorer-mba root-cause analysis — msg#11713, #11681,
  #11724
- head-mba design principles + Phase 4 playbook — msg#11722,
  #11747, #11785, #11791
- head-mba naming direction (`fleet-health-daemon`) — msg#11785
- head-spartan Spartan constraint matrix — msg#11753
- head-spartan concurrent-instance incident → scitex-orochi#144
  — msg#11708
- ywatanabe reframe directive — msg#11775, #11779, #11783, #11789
- todo-manager triage + phasing — msg#11778, #11782

Draft ends here.
