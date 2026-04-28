---
name: orochi-fleet-role-taxonomy-tags-and-agent-roster
description: Function tags (orthogonal, multi-assign) + agent-layer self-tagging examples. (Split from 45_fleet-role-taxonomy-tags-and-roster.md.)
---

> Sibling: [`69_fleet-role-taxonomy-process-roster-and-anti-patterns.md`](69_fleet-role-taxonomy-process-roster-and-anti-patterns.md) for process-layer roster, anti-patterns, related skills.
## Function tags (orthogonal, multi-assign)

Roles answer "what layer and what protocol". Function tags answer
"what does this specific agent/daemon do". A single entity can
carry multiple function tags.

Canonical tag vocabulary:

| Tag                 | Meaning                                                                     |
|---------------------|-----------------------------------------------------------------------------|
| `prober`            | Active liveness verification (DM ping, regex probe, etc.)                   |
| `auditor`           | Retroactive correctness checks (close-evidence, drift, dedupe)              |
| `dispatcher`        | Work routing (function tag on `lead`, not a separate role)                  |
| `skill-sync`        | Skill library CRUD + aggregation + rsync                                    |
| `healer`            | Operational recovery of stuck/dead agents                                   |
| `verifier`          | Playwright / screenshot / real-browser confirmation                         |
| `explorer`          | Codebase reconnaissance, open-ended research                                |
| `researcher`        | Literature / PubMed / external reference gathering                          |
| `quality-checker`   | Code / output quality review                                                |
| `newbie-sim`        | Clueless-first-user simulator (behavioral test rig)                         |
| `auth`              | Credential / permission bootstrap (e.g. `scitex-slurm-perms.service`)       |
| `sync`              | Cross-host file/state synchronization                                       |
| `sweep`             | Periodic scan + cleanup of stale artifacts                                  |
| `metrics-collector` | Deterministic self-describe daemon family (ywatanabe msg#11483)             |
| `slurm-resource-scraper` | Per-user SLURM allocation / queue / walltime scraper (Spartan + NAS + WSL) |
| `host-self-describe` | OS / hardware / tunnel / docker / SLURM state scraper (msg#11483)          |
| `fleet-watch`       | Per-host outbound reachability producer (already running on NAS)            |
| `reverse-tunnel`    | Autossh-style inbound SSH exposure via MBA bastion                          |
| `tunnel`            | Cloudflared / bastion tunnel management (generic)                           |
| `prompt-actuator`   | Prompt unblocker daemon (existing NAS `fleet-prompt-actuator.timer`)        |
| `storage-host`      | Host offers shared storage (NAS)                                            |
| `daemon-host`       | Host is designated to run daemon-layer processes                            |
| `docker-host`       | Host runs hub / stable / dev Docker containers                              |
| `hpc-host`          | Host provides HPC compute (Spartan / Gadi / etc.)                           |
| `verifier-host`     | Host can run playwright / real browser sessions                             |
| `windows-host`      | Host is Windows/WSL                                                         |
| `taxonomy-curator`  | Owns the fleet role taxonomy + fleet-members roster                         |
| `quota-watcher`     | Tracks Claude 5h / weekly quota windows                                     |

The same `prober` function can be attached to a `worker` (healer's
DM ping + LLM classification) or to a `daemon` (deterministic
pane-state regex loop). Either placement is legitimate — the
choice is an implementation detail (LLM-in-loop or not), and the
role follows from that automatically.

## Fleet self-tagging (agent layer)

The final mapping lives in `fleet-members.md`; this table is the
snapshot at the moment of taxonomy ratification so provenance is
intact. See `fleet-members.md` for the live copy.

| Agent                      | Role     | Function tags                                   |
|----------------------------|----------|-------------------------------------------------|
| head-mba                   | lead     | [dispatcher, docker-host]                       |
| head-mba                   | head     | [verifier-host]                                 |
| head-nas                   | head     | [storage-host, daemon-host, docker-host]        |
| head-spartan               | head     | [hpc-host, slurm-resource-scraper]              |
| head-ywata-note-win        | head     | [windows-host]                                  |
| mamba-skill-manager-mba    | worker   | [skill-sync, taxonomy-curator]                  |
| mamba-todo-manager-mba     | worker   | [dispatcher, auditor]                           |
| mamba-healer-mba           | worker   | [prober, healer]                                |
| mamba-healer-nas           | worker   | [prober, healer]                                |
| mamba-synchronizer-mba     | worker   | [sync, auditor]                                 |
| mamba-auth-manager-mba     | worker   | [auth, quota-watcher]                           |
| mamba-explorer-mba         | worker   | [explorer, researcher]                          |
| mamba-verifier-mba         | worker   | [verifier]                                      |
| mamba-quality-checker-mba  | worker   | [quality-checker, auditor]                      |
| mamba-newbie-mba           | worker   | [newbie-sim]                                    |

`head-mba` appears twice because one agent literally fills two
roles right now (lead + own-host head). This is not ideal but is
explicit, not accidental.

