<!-- ---
!-- Timestamp: 2026-04-16 22:48:26
!-- Author: ywatanabe
!-- File: /home/ywatanabe/proj/scitex-orochi/src/scitex_orochi/_skills/scitex-orochi/00-agent-types/99-template.md
!-- --- -->


---
name: agent-type-TEMPLATE
description: Template for defining a new agent type.
---

# <Type Name>

## Category
<Communicator | Dedicated Scope | Repetitive Tasks>

## Roles
- <primary responsibility>

## Tasks
- <concrete tasks this agent type performs>

## Default Communicators
- To: <targets>
- From: <sources>

## Escalation path
- → <chain>

## Lifetime
- <Persistent | Session-scoped | Ephemeral>

## Placement
- <placement rule>

## Naming
- Naming: `<prefix>-<variable>-<host>`
- Example: `<example>`

## Cardinality
- <exactly 1 | 1 per X | few | many>

<!-- EOF -->