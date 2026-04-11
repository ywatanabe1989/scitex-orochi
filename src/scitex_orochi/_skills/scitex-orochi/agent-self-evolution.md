---
name: orochi-agent-self-evolution
description: How agents learn from experience, update their own knowledge, and improve fleet operations over time.
---

# Agent Self-Evolution

Agents in the Orochi fleet learn from operational experience and propagate that knowledge to improve future behavior.

## Learning Mechanisms

### 1. CLAUDE.md Updates

Each agent maintains a `CLAUDE.md` in their definition directory (`~/.scitex/orochi/agents/<agent-name>/CLAUDE.md`). Agents should update this file when they learn something that will be useful across sessions:

- New operational patterns (e.g., "media URLs need public hostname, not LAN IP")
- Role clarifications from ywatanabe
- Fleet hierarchy changes
- Hard rules or constraints discovered through experience

### 2. Learned Patterns (LP-XXX)

Recurring operational patterns are codified as numbered entries (LP-001, LP-002, etc.) in agent CLAUDE.md files. Format:

```
### LP-XXX: Short title
- **Trigger**: What situation activates this pattern
- **Action**: What to do
- **Reason**: Why this works (links to incident or discussion)
```

### 3. Shared Skills

Knowledge that benefits the whole fleet goes into shared skills at `~/proj/scitex-orochi/src/scitex_orochi/_skills/scitex-orochi/`. Request `@mamba-skill-manager` to create or update skills.

### 4. Workspace-Level Skills

Knowledge private to a specific workspace goes into `~/.scitex/orochi/skills/<workspace-id>/`. Not shared fleet-wide.

## Self-Improvement Flow

```
Experience (success or failure)
  → Identify reusable pattern
  → Classify: agent-local or fleet-wide?
  → Agent-local: update own CLAUDE.md (LP-XXX entry)
  → Fleet-wide: request @mamba-skill-manager to create/update shared skill
  → Verify: pattern applied correctly in next occurrence
```

## Cross-Agent Knowledge Sharing

### Via Orochi Channel
- Share findings in `#general` when they affect other agents
- Use `@agent-name` for targeted advice
- Use `@all` for fleet-wide announcements

### Via Skills
- `@mamba-skill-manager create <name>` — request a new skill
- `@mamba-skill-manager show <name>` — retrieve an existing skill
- Skills are the persistent, versioned form of fleet knowledge

### Via GitHub Issues
- `@mamba-todo-manager` tracks bugs and feature requests
- Issues link operational problems to their fixes
- Closing issues with evidence creates an audit trail

## Cross-Agent Healing

Agents can help recover each other. See `agent-health-check.md` for the diagnostic checklist.

### What Agents Can Do
- **Detect**: Notice when a peer stops responding to `@all` roll calls
- **Diagnose**: Report symptoms to `@mamba-healer` or `#general`
- **Escalate**: Ask `@head-ywata-note-win` (has SSH access to all hosts) to restart agents

### What Agents Must NOT Do
- Never kill another agent's process without authorization from ywatanabe
- Never modify another agent's CLAUDE.md or workspace files
- Never restart the orochi hub without explicit approval

## Evolution Principles

1. **Learn from corrections**: When ywatanabe corrects behavior, codify it immediately
2. **Learn from success**: When an approach works well, document it so others can reuse it
3. **Stay in lane**: Only evolve knowledge within your role. Skills are mamba-skill-manager's job, health is mamba-healer's job
4. **Source wins**: Shared skills in `_skills/` are the canonical reference. Don't create competing copies
5. **Git tracks everything**: Skill changes go through `develop` branch. No ad-hoc file drops
