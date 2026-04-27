---
name: orochi-fleet-health-daemon-design
description: DRAFT — design doc for the fleet-health-daemon (todo#146). Orchestrator that links the four sub-files (overview, phases, recovery, deployment). Cross-references to `fleet-health-daemon-design.md §N.M` resolve to the corresponding sub-file (see section-map below).
---

# fleet-health-daemon — Design (todo#146)

> **STATUS: DRAFT** design doc for `ywatanabe1989/todo#146`. Posted to
> #agent for fleet review before PR. Not canonical until ywatanabe GO +
> merge into the `_skills/scitex-orochi/` tree.

This file was split for the 512-line markdown limit. Content lives in
four focused sub-files; this orchestrator is the entry point and the
section-number → sub-file map.

## Sub-files

- [fleet-health-daemon-design-overview](fleet-health-daemon-design-overview.md) —
  §0 ground rules, §1 TL;DR, §2 origin, §3 3-layer architecture
  (process daemon + mamba-healer worker mesh + ledger).
- [fleet-health-daemon-design-phases](fleet-health-daemon-design-phases.md) —
  §4 Phase 1 (Claude Code quota-state scraping, NDJSON schema v3,
  threshold breadcrumbs, hub aggregation), §5 Phase 2 (multi-signal
  health probe), §6 Phase 3 (mamba-healer-`<host>` consumer + mesh
  redundancy).
- [fleet-health-daemon-design-recovery](fleet-health-daemon-design-recovery.md) —
  §7 Phase 4 recovery action playbook: §7.1 permission-prompt,
  §7.2 extra-usage wedge, §7.3 context-window-full, §7.4 tmux-stuck,
  §7.5 MCP zombie, §7.6 paste-buffer-unsent, §7.7 periodic
  resurrection sweep. Includes the 2026-04-15 motivating incident.
- [fleet-health-daemon-design-deployment](fleet-health-daemon-design-deployment.md) —
  §8 host-specific deployment + Spartan constraint matrix, §9 nice/
  IO/resource discipline, §10 cross-host coverage, §10A probe vs
  pane-state liveness divergence (4-quadrant matrix), §11
  anti-patterns, §12 open questions, §13 implementation order,
  §14 related skills / issues.

## Phasing summary

- **Phase 0** (this design): naming locked, 2-layer taxonomy, Spartan
  matrix integrated.
- **Phase 1**: Claude Code quota-state scraping (immediate deliverable;
  subsumes scitex-orochi#272 / #430).
- **Phase 1b**: absolute quota limits via Anthropic API or
  `quota-limits.md` known-constant fallback.
- **Phase 2**: full multi-signal probe (docker stats, cpu.pressure,
  systemd units, MCP dedup, pane state).
- **Phase 3**: worker-side consumer — extend mamba-healer agents to
  read daemon NDJSON + breadcrumbs and cross-probe peers.
- **Phase 4**: executable recovery playbook + periodic resurrection
  sweep.

See the corresponding sub-files for full detail.
