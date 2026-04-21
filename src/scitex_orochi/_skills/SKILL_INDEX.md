# scitex-orochi Skill Index

One-line role per skill file shipped inside `scitex_orochi/_skills/`.
A fleet agent looking for "cli convention", "health probe", "agent
types", etc. can grep this single index and land directly on the right
file.

> This file is validated by `tests/cli/test_skill_index.py` — every
> `.md` under `scitex_orochi/_skills/` must appear here. Add new
> skills to the table in the same commit that creates them.

Canonical package skill root: `src/scitex_orochi/_skills/scitex-orochi/`
(plus the root-level `SKILL.md` entry point).

## Package entry point

| File | Role |
|---|---|
| `scitex-orochi/SKILL.md` | Package skill entry point; links to every sub-skill below. |

## Agent patterns

| File | Role |
|---|---|
| `scitex-orochi/agent-deployment.md` | How to launch autonomous agents (push / poll modes, MCP config). |
| `scitex-orochi/agent-health-check.md` | 8-step fleet agent health checklist with copy-paste commands. |
| `scitex-orochi/agent-self-evolution.md` | How agents learn, share knowledge, and improve fleet operations. |
| `scitex-orochi/agent-pane-state-patterns.md` | Regex catalog for classifying terminal pane state. |
| `scitex-orochi/agent-permission-prompt-patterns.md` | Claude Code permission-prompt regexes and recovery. |
| `scitex-orochi/permission-prompt-patterns.md` | Generic permission-prompt regex catalog (non-agent specific). |
| `scitex-orochi/subagent-reporting-discipline.md` | How subagents report back — format, scope, silent success. |

## Agent taxonomy

| File | Role |
|---|---|
| `scitex-orochi/00-agent-types/README.md` | Agent-type index — daemon / lead / head / worker / proj / expert. |
| `scitex-orochi/00-agent-types/00-fleet-lead.md` | `lead` role definition. |
| `scitex-orochi/00-agent-types/01-head.md` | `head-<host>` role definition. |
| `scitex-orochi/00-agent-types/02-proj.md` | `proj-*` role definition. |
| `scitex-orochi/00-agent-types/03-expert.md` | `expert-*` role definition. |
| `scitex-orochi/00-agent-types/04-worker.md` | `worker-*` role definition. |
| `scitex-orochi/00-agent-types/05-daemon.md` | `daemon` role definition. |
| `scitex-orochi/00-agent-types/90-policies.md` | Cross-role fleet policies. |
| `scitex-orochi/00-agent-types/99-template.md` | Template for adding a new agent type. |
| `scitex-orochi/fleet-role-taxonomy.md` | Narrative introduction to the role taxonomy above. |

## Conventions

| File | Role |
|---|---|
| `scitex-orochi/convention-cli.md` | **CLI noun-verb convention — canonical source of truth (Phase 1d).** |
| `scitex-orochi/convention-env-vars.md` | `SCITEX_OROCHI_*` env-var naming, location, and change discipline. |
| `scitex-orochi/convention-python-venv.md` | Version-tagged Python venv chain with symlinks. |
| `scitex-orochi/convention-quality-checks.md` | Fleet-wide quality monitoring and smoke-test patterns. |
| `scitex-orochi/convention-connectivity-probe.md` | `bash -lc` SSH probe pattern, cross-OS metric semantics. |

## Fleet design / daemons

| File | Role |
|---|---|
| `scitex-orochi/fleet-operating-principles.md` | Fleet-wide rules: mutual aid, ship-next, priority matrix. |
| `scitex-orochi/fleet-skill-manager-architecture.md` | Hybrid agent/daemon split for skill lifecycle. |
| `scitex-orochi/fleet-hungry-signal-protocol.md` | Layer-2 hungry-signal protocol (idle-head → lead). |
| `scitex-orochi/fleet-health-daemon-design.md` | Fleet-health daemon overall design. |
| `scitex-orochi/fleet-health-daemon-design-overview.md` | Fleet-health daemon — scope + goals. |
| `scitex-orochi/fleet-health-daemon-design-phases.md` | Fleet-health daemon — phased rollout plan. |
| `scitex-orochi/fleet-health-daemon-design-deployment.md` | Fleet-health daemon — deployment layout. |
| `scitex-orochi/fleet-health-daemon-design-recovery.md` | Fleet-health daemon — recovery / resurrection. |
| `scitex-orochi/skill-manager-architecture.md` | Historical skill-manager architecture note. |

## HPC

| File | Role |
|---|---|
| `scitex-orochi/hpc-etiquette.md` | HPC etiquette umbrella doc. |
| `scitex-orochi/hpc-etiquette-general.md` | General HPC etiquette: no `find /`, modules, quotas. |
| `scitex-orochi/hpc-etiquette-guardrails.md` | HPC guardrails against accidental abuse. |
| `scitex-orochi/hpc-etiquette-spartan-policy.md` | Spartan-cluster-specific policy extensions. |
| `scitex-orochi/hpc-spartan-startup-pattern.md` | Spartan Lmod module chain, login vs compute, LD_LIBRARY_PATH. |
| `scitex-orochi/slurm-resource-scraper-contract.md` | SLURM resource-scraper data contract. |

## Product / UX

| File | Role |
|---|---|
| `scitex-orochi/product-dashboard-features.md` | Chat, Agents tab, element inspector, TODO, settings. |
| `scitex-orochi/product-compute-resources.md` | Hardware requirements, host roles, scaling advice. |
| `scitex-orochi/product-scientific-figure-standards.md` | Sample size, stats rules, figure-layout standards. |
| `scitex-orochi/paper-writing-discipline.md` | Fleet paper-writing discipline (when on a paper branch). |

## Meta / governance

| File | Role |
|---|---|
| `scitex-orochi/skills-public-vs-private.md` | Where to put a skill: shipped package vs `~/.scitex/<pkg>/`. |
| `scitex-orochi/legacy/00-agent-types_01.md` | Historical snapshot of the agent-types skill. |

## Adding a new skill

1. Drop the new `.md` under `src/scitex_orochi/_skills/scitex-orochi/`
   (or a sub-directory).
2. Add a one-line row to the appropriate table above.
3. Link it from `scitex-orochi/SKILL.md` if it belongs in the canonical
   sub-skill list.
4. Run `pytest tests/cli/test_skill_index.py` — it will fail until the
   new file is indexed.
