<!-- ---
!-- Timestamp: 2026-04-16 23:56:03
!-- Author: ywatanabe
!-- File: /home/ywatanabe/proj/scitex-orochi/src/scitex_orochi/_skills/scitex-orochi/00-agent-types/02-proj.md
!-- --- -->


---
name: agent-type-proj
description: Proj agent — project-scoped, dedicated to a single repo with deep codebase context.
---

# Project-specific Agent

## Category
Dedicated Scope

## Roles
- Copilot dedicated for a git-managed project

## Tasks
- Lives in `#proj-<project>` channel
- Must work from project root with .git directory
- Must have deep codebase context
- Works as a communication interface to the user for the project channel

## Default Communicators
- To: user, lead, head, worker
- From: user, head, worker

## Permissions
- Full

## Escalation path
- → lead → user
- → user (direct when lead not responsive)

## Lifetime
- Persistent

## Placement
- On the host where the project repo mainly lives

## Naming
- Naming: `proj-<project>-<host>`
- Example: `proj-my-package-host-a`, `proj-my-paper-host-b`

## Cardinality
- 1 per project

<!-- EOF -->