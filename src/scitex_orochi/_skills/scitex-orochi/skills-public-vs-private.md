---
name: skills-public-vs-private
description: Where an Orochi skill belongs — shipped with the package (public) or ~/.scitex/orochi/shared/skills/scitex-orochi-private/ (private).
---

# Public vs Private Skills — Orochi

For the general decision rule and layout, see
`scitex:general/skills-public-vs-private.md`. This page is the
Orochi-specific application.

## Two locations

| Kind | Source of truth | Exported to |
|---|---|---|
| **Public** | `src/scitex_orochi/_skills/scitex-orochi/` (in this repo) | `~/.claude/skills/scitex/scitex-orochi/` via `scitex-dev skills export --package scitex-orochi` |
| **Private** | `~/.scitex/orochi/shared/skills/scitex-orochi-private/` (in dotfiles) | `~/.claude/skills/scitex/scitex-orochi-private/` via symlink |

Private `SKILL.md` sets `user-invocable: false`.

## Rule of thumb

A skill is **private** if it names:

- Specific hosts (`mba`, `spartan`, `ywata-note-win`, `nas`)
- Specific container names (`orochi-server-stable`)
- Specific credentials (Cloudflare API keys, SSH keys)
- Specific zone IDs or tunnel IDs
  (e.g. `2eda29d603d74180011e6711ffff65a3`)
- Fleet agent roster, incidents, or per-host deploy paths

Otherwise public. The public form describes *patterns*, the private
form describes *operational recipes on named infrastructure*.

## Orochi examples

| Skill | Public or private | Why |
|---|---|---|
| `agent-deployment.md` | public | Describes launch modes and MCP config generically |
| `agent-health-check.md` | public | Generic 8-step checklist |
| `pane-state-patterns.md` | public | Regex catalog, no hosts |
| `infra-hub-docker-disk-full.md` | private | Names mba, colima VM, `orochi-server-stable`, CF zone |
| `infra-hub-deploy-hotfix.md` | private | Names mba, NAS, container name |
| `fleet-members.md` | private | Agent roster |
| `infra-secrets-location.md` | private | Credential paths |

## What happened with `hub-docker-deploy.md`

Added to this public skill index in PR #224. Audit (2026-04-18) found
it referenced `mba`, `orochi-server-stable`, the Cloudflare zone ID,
and mba-specific `/Users/` paths. Moved to
`~/.scitex/orochi/shared/skills/scitex-orochi-private/infra-hub-docker-disk-full.md`,
index entry dropped from public SKILL.md. Lesson: audit for
fleet-internal nouns **before** adding a public skill entry.

## Grep check before publishing

```bash
cd ~/proj/scitex-orochi
grep -rEn 'mba|spartan|ywata-note-win|orochi-server-stable|zones/[a-f0-9]{32}|CLOUDFLARE_API_KEY' \
  src/scitex_orochi/_skills/
# Expected: no matches. Any hit is either rewritable or should move
# to scitex-orochi-private.
```

## Cross-references

- `scitex:general/skills-public-vs-private.md` — canonical decision rule
- `scitex:general/interface-skills.md` — `_skills/` layout
- `scitex:general/how-to-update-skills.md` — edit sources, export workflow
