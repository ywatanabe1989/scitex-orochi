<!-- ---
-- Timestamp: 2026-04-16 22:30:00
-- Author: ywatanabe
-- File: /home/ywatanabe/proj/scitex-orochi/src/scitex_orochi/_skills/scitex-orochi/00-agent-types/05-daemon.md
-- --- -->

---
name: agent-type-daemon
description: Daemon — deterministic programmatic loop, no Claude session, zero quota.
---

# Daemon

## Category
Repetitive Tasks

## Roles
- Not an agent
- Deterministic, programmatic loop
- No Claude session, zero quota

## Tasks

## Default Communicators
- To: log files, touch-files, git commits, API responses (structured, no chat)
- From: API calls, cron triggers, file watches (no chat)

## Permissions
- File I/O on own host
- No chat, no WebSocket, no Claude session

## Autonomy
- Fully autonomous within its loop
- Does not self-escalate; failures detected by agent-layer healers

## Escalation path
- → (detected by worker-healer) → head → lead → user

## Lifetime
- Persistent (systemd/launchd/cron)

## Quota expectation
- Zero

## Placement
- Choose by cost, not convenience (see Daemon Host Policy)

## Naming
- Naming: `daemon-<name>` or `<name>.timer` / `<name>.service`
- Example: `audit-closes.timer`, `skill-sync-daemon`

## Cardinality
- many

<!-- EOF -->
