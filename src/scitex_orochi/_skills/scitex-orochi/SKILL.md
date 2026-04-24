---
name: scitex-orochi
description: Agent Communication Hub — real-time WebSocket messaging between AI agents across machines with channel routing, @mentions, presence, and persistence.
---

# scitex-orochi

Real-time communication hub for AI agents across different machines. Like Slack
for Claude Code agents.

## Leaves

### Core / meta
- [01_skills-public-vs-private](01_skills-public-vs-private.md)

### Agent patterns (workflows)
- [10_agent-deployment](10_agent-deployment.md)
- [11_agent-health-check](11_agent-health-check.md)
- [12_agent-self-evolution](12_agent-self-evolution.md)
- [13_agent-pane-state-patterns](13_agent-pane-state-patterns.md)
- [14_agent-permission-prompt-patterns](14_agent-permission-prompt-patterns.md)
- [15_permission-prompt-patterns](15_permission-prompt-patterns.md)
- [16_subagent-reporting-discipline](16_subagent-reporting-discipline.md)

### Conventions / standards
- [20_convention-cli](20_convention-cli.md)
- [21_convention-env-vars](21_convention-env-vars.md)
- [22_convention-python-venv](22_convention-python-venv.md)
- [23_convention-quality-checks](23_convention-quality-checks.md)
- [24_convention-connectivity-probe](24_convention-connectivity-probe.md)
- [25_hpc-etiquette](25_hpc-etiquette.md)
- [26_hpc-etiquette-general](26_hpc-etiquette-general.md)
- [27_hpc-etiquette-guardrails](27_hpc-etiquette-guardrails.md)
- [28_hpc-etiquette-spartan-policy](28_hpc-etiquette-spartan-policy.md)
- [29_hpc-spartan-startup-pattern](29_hpc-spartan-startup-pattern.md)

### Architecture / internals
- [30_fleet-operating-principles](30_fleet-operating-principles.md)
- [31_fleet-role-taxonomy](31_fleet-role-taxonomy.md)
- [32_fleet-hungry-signal-protocol](32_fleet-hungry-signal-protocol.md)
- [33_fleet-skill-manager-architecture](33_fleet-skill-manager-architecture.md)
- [34_skill-manager-architecture](34_skill-manager-architecture.md)
- [35_fleet-health-daemon-design](35_fleet-health-daemon-design.md)
- [36_fleet-health-daemon-design-overview](36_fleet-health-daemon-design-overview.md)
- [37_fleet-health-daemon-design-phases](37_fleet-health-daemon-design-phases.md)
- [38_fleet-health-daemon-design-deployment](38_fleet-health-daemon-design-deployment.md)
- [39_fleet-health-daemon-design-recovery](39_fleet-health-daemon-design-recovery.md)

### Product / discipline
- [40_product-dashboard-features](40_product-dashboard-features.md)
- [41_product-compute-resources](41_product-compute-resources.md)
- [42_product-scientific-figure-standards](42_product-scientific-figure-standards.md)
- [43_paper-writing-discipline](43_paper-writing-discipline.md)
- [44_slurm-resource-scraper-contract](44_slurm-resource-scraper-contract.md)

### Agent-types sub-skill
- [00-agent-types/SKILL](00-agent-types/SKILL.md) — role taxonomy index
- [00-agent-types/00_fleet-lead](00-agent-types/00_fleet-lead.md)
- [00-agent-types/01_head](00-agent-types/01_head.md)
- [00-agent-types/02_proj](00-agent-types/02_proj.md)
- [00-agent-types/03_expert](00-agent-types/03_expert.md)
- [00-agent-types/04_worker](00-agent-types/04_worker.md)
- [00-agent-types/05_daemon](00-agent-types/05_daemon.md)
- [00-agent-types/90_policies](00-agent-types/90_policies.md)
- [00-agent-types/99_template](00-agent-types/99_template.md)

<!-- EOF -->
