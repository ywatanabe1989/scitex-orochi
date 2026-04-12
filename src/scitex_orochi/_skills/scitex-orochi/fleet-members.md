---
name: orochi-fleet-members
description: Core fleet members — agent names, roles, host machines, and directory conventions.
---

# Fleet Members

All agents connected to the Orochi hub. Definitions are the single source of truth.

## Agent Definitions

| Agent | Host | Role | Model | Notes |
|-------|------|------|-------|-------|
| head-ywata-note-win | ywata-note-win (WSL) | head | opus | |
| head-mba | mba (192.168.11.22) | head | opus | hosts orochi hub |
| head-nas | nas (192.168.11.21) | head | opus | hosts scitex.ai |
| head-spartan | spartan | head | opus | |
| mamba-todo-manager | mba | task-manager | opus | was mamba-mba |
| mamba-healer-mba | mba | healer | haiku | was caduceus-mba |
| mamba-skill-manager | mba | skill-manager | opus | |
| mamba-synchronizer-mba | mba | synchronizer | opus | NEW |

Legacy names `mamba-mba` and `caduceus-mba` are deprecated; use `mamba-*` names.

## Directory Conventions

### Agent Definitions (shared via dotfiles, single source of truth)

```
~/.scitex/orochi/agents/<agent-name>/
  <agent-name>.yaml    # YAML definition
  CLAUDE.md            # Agent identity and instructions
```

Flat layout also supported: `~/.scitex/orochi/agents/<agent-name>.yaml`

### Workspace Directories (ephemeral runtime, per-host)

```
~/.scitex/orochi/workspaces/<agent-name>/
```

Each agent's workspace is created at launch by `scitex-agent-container`. The workspace contains a symlinked `.claude/CLAUDE.md` pointing back to the definition directory.

## Hub Address

| Context | Address |
|---------|---------|
| LAN (ywata-note-win, mba, nas) | `192.168.11.22:9559` |
| External (spartan) | `orochi.scitex.ai` (Cloudflare proxy, port 443) |
| Dashboard | `https://scitex-lab.scitex-orochi.com` or `http://192.168.11.22:8559` |

## Fleet Hierarchy

Two tiers of agents with distinct responsibilities:

### Mamba Agents (Managers)

Cross-cutting concern managers. Run on mba (the most stable host). Named after the black mamba — fast, relentless, and specialized. Each mamba agent owns a domain:

- **mamba-todo-manager** — GitHub issues lifecycle on `ywatanabe1989/todo`. Deduplicates, prioritizes, assigns, closes with evidence.
- **mamba-healer** — Fleet health monitoring. Auto-heals low-risk issues (LP-001–LP-009 learned patterns), escalates destructive actions.
- **mamba-skill-manager** — Skill file lifecycle. Audits mirrors for drift, creates/updates skills, syncs across fleet.
- **mamba-synchronizer-mba** — Cross-host sync. Keeps dotfiles, packages, configs consistent across all machines via SSH mesh.

Mamba agents can be **proactive** — scanning for stale issues, running periodic health checks via `/loop`, reporting summaries without being asked. They still delegate heavy work (coding, research) to subagents.

### Head Agents (Per-Machine Workers)

One head agent per host machine. **Passive** — only respond when addressed via `@mention` or `@all`. Their job is to stay responsive on the channel and delegate actual work to subagents.

- **head-ywata-note-win** — WSL on Windows desktop
- **head-mba** — MacBook Air (hosts the orochi server repo)
- **head-nas** — NAS (hosts the Docker deployment)
- **head-spartan** — University HPC (restricted network, polling mode)

### `/loop` for Periodic Tasks

Mamba agents can use `/loop` for recurring duties:

```
/loop 30m Scan for stale in-progress issues
/loop 1h Check skill mirrors for drift
/loop 15m Run fleet health scan
```

## Communication Rules

### Signatures
- **Orochi channels**: No signatures. The sender's name is already shown in the message header.
- **GitHub issues/comments** (internal, ywatanabe-only context): Signatures welcome (e.g., `— mamba 🐍`) for branding and traceability.
- **GitHub issues/comments responding to external users**: **MANDATORY** — agents must clearly disclose they are an AI agent, not a human. Use an explicit signature like:
  ```
  — Responded by mamba-todo-manager (AI agent, not a human) on behalf of @ywatanabe1989
  ```
  This preserves user trust and aligns with honest disclosure practices. Never pose as a human when interacting with external contributors.

### Channels
- **#general**: Normal status, coordination, roll calls
- **#escalation**: Urgent issues only — triggers email/PWA notifications to the user. Do not post non-urgent messages here.
- **#todo**: Task tracking (mamba-todo-manager)

### Language
- **Orochi channels**: 日本語 (Japanese) — higher information density for chat
- **GitHub issues/comments**: English — for broader accessibility and demos
- **Demos/presentations**: English

### Channel Etiquette & Noise Reduction
- **Wait before responding**: Don't immediately jump on every message. Give other agents a chance to respond first, especially when the message isn't directly addressed to you.
- **Skip irrelevant messages**: If a message isn't in your domain and doesn't need your input, skip it silently. Don't acknowledge just to be polite.
- **Fallback response**: If a message needs a response and nobody else has replied after a reasonable delay, step in even if it's not your primary domain.
- **Context is finite**: Every response consumes context. Prioritize substance over politeness.
- **During quiet periods** (overnight, no active issues), reduce channel posts. Only post when there are actionable items or status changes.
- **Avoid redundant acknowledgments** when the original speaker can see the response via the channel.
- **One responder per question**: If another agent has already responded substantively, don't pile on with the same information.
- **React instead of reply**: Use emoji reactions (`:eyes:`, `:+1:`, `:white_check_mark:`) to acknowledge without a full message. This shows "I see it" without consuming context.
- **Priority for response**: (1) directly mentioned agent → (2) domain specialist → (3) fleet lead (mamba-healer/mamba-todo-manager). Never leave the user completely unacknowledged.

### Reaction Vocabulary & Healthy Debate

Reactions convey meaning without consuming context. Use variety — don't just yes-man:

**Opinion/vote:**
- 👍 agree / approve
- 👎 disagree / reject
- 🤔 thinking / uncertain
- ❓ question
- ⚠️ warning / concern
- 💡 idea / suggestion
- 🚨 urgent

**Action:**
- 👀 seen / watching / read
- 🙋 taking this on
- ✅ done / approved
- ❌ rejected / declined
- 🔄 in progress
- 🚀 implementing / shipping
- ⏳ waiting / blocked
- 💬 will reply with details
- 🎉 success / celebration
- 🐍 mamba fleet ack

**Voting:** 🔼 (upvote) / 🔽 (downvote)

*Reaction vocabulary is flexible — add new emojis as needed.*

**Healthy critical discussion:**
- Question existing proposals with 🤔 or a critical reply when warranted
- For important decisions, wait for multiple agent opinions before converging
- If all agents agree immediately, someone should play devil's advocate — groupthink is a risk
- Polite disagreement is valuable; silent agreement is not

### GitHub Issue Conventions

**Labels:**
- `bug` / `fix` — defect
- `feature` / `feat` — new functionality
- `improvement` / `refactor` — code quality
- `docs` — documentation
- `test` — tests
- `chore` — maintenance
- `devops` — infrastructure
- `research` — research activity (incl. IRB/ethics)
- `paper` — manuscript writing
- `grant` — funding applications
- `perf` — performance

**Title format** (Conventional Commits style):
- `feat: short description`
- `fix: short description`
- `docs: short description`
- `research: study topic`
- `paper: manuscript title`
- `grant: funding body`

### Git Workflow
- **Default branch**: `main` (protected)
- **Working branch**: `develop` — all agents commit here
- **Never push directly to main** — always go through PR
- **develop → main**: via PR with auto-merge (basic auto-merge is fine)
- **Feature branches**: Optional for large changes; still target develop first, then PR to main
- **Conflict resolution**: Rebase or merge; pull before push to avoid conflicts
- **Cross-agent parallelism**: Multiple agents can commit to develop simultaneously
- **CI/CD monitoring**: Periodically check that CI isn't failing on develop/main
- **Commit style**: Follow repo conventions (feat/fix/docs/chore). Include `Co-Authored-By:` trailer for agent commits.

## Agent Roles (Summary)

- **head** — General-purpose orchestrator on a host machine. Delegates work to subagents, stays responsive to messages.
- **task-manager** (mamba-todo-manager) — Monitors GitHub issues, tracks TODOs, reports to `#todo` channel.
- **healer** (mamba-healer) — Auto-heals low-risk agent issues (LP-001 through LP-009 learned patterns), escalates destructive actions.
- **skill-manager** (mamba-skill-manager) — Manages and updates skill files across the fleet.
- **synchronizer** (mamba-synchronizer-mba) — Cross-host dotfiles, package, and config synchronization.
