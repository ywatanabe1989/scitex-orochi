---
name: orochi-convention-connectivity-probe-adoption
description: Adoption checklist + per-host status + per-lane issue templates + related skills. (Split from 59_convention-connectivity-probe-extras.md.)
---

> Sibling: [`76_convention-connectivity-probe-cross-os.md`](76_convention-connectivity-probe-cross-os.md) for cross-OS semantics + common mistakes.

## Adoption Checklist

Every fleet healer and fleet_watch-style loop must satisfy all of these before being considered canonical. Use this list when updating an existing `/loop` prompt.

- [ ] **Remote command wrap**: every `ssh host 'cmd'` call uses `bash -lc 'cmd'`.
- [ ] **SSH flags**: `ConnectTimeout=5`, `BatchMode=yes`, `StrictHostKeyChecking=accept-new`, `ServerAliveInterval=5`, `ServerAliveCountMax=1` on every probe.
- [ ] **Three-outcome schema**: SSH failure, command error, and command success are all distinguished — never collapse to a single "0" that means "unknown".
- [ ] **Compound escalation gate**: no host is marked down on a single metric. Minimum compound condition = `ssh=down` **AND** (`claude_procs=0` **OR** `orochi_presence=absent`).
- [ ] **Silent success**: routine all-green scans are written to a local log file only, never posted to any channel (see `fleet-communication-discipline.md` rule #6).
- [ ] **Snapshot reuse**: before running a fresh probe, check whether head-<host>'s `fleet_watch.sh` already captured the same data in `~/.scitex/orochi/fleet-watch/`. If yes, read the snapshot instead.
- [ ] **Host-specific gotchas**:
  - primary workstation: confirm `ssh <host> 'bash -lc "env | grep TMUX"'` shows `TMUX_TMPDIR`.
  - Spartan: probe login1 only, never compute nodes. Respect `project_spartan_login_node` memory.
  - WSL hosts: remote aliases may route via cloudflared bastion, not LAN IP (see #292/#301 for history).
  - NAS/storage hosts: `tmux` may run under a different user's socket; confirm before escalating on `tmux_count=0`.

## Per-host adoption status

Tracked 2026-04-13. Agents responsible for each lane must update this list when they land changes.

| Host | Healer | Canonical compliant? | Notes |
|---|---|---|---|
| host-a (WSL) | worker-healer-<host-a> | ✅ 2026-04-13 (cron job 40c61ea4 / msg#8406) | `bash -lc`, compound gate, silent success verified |
| host-b (primary workstation) | worker-healer-<host-b> | 🔄 in-progress (2026-04-13) | Owner: head-<host-b>. Canonical /loop prompt drafted by worker-skill-manager; head-<host-b> to apply. |
| host-c (NAS/storage) | worker-healer-<host-c> | ⏳ pending (depends on fleet_watch snapshot reuse) | Owner: head-<host-c>. Consume `~/.scitex/orochi/fleet-watch/` instead of re-probing. |
| host-d (HPC cluster) | head-<host-d> (no worker-healer yet) | ⏳ feasibility note only | Constraint: login-node-only, never compute nodes. Probe must use `bash -lc`. |

## Per-lane issue templates

Copy-paste these into the issue tracker (or DM the host owner) when assigning adoption work to a host owner. (`#agent` was abolished 2026-04-21; cross-head coordination now lives in `#heads`.)

### Primary workstation lane (owner: head-<host>)
> **Task**: Align `worker-healer-<host>` `/loop` with `convention-connectivity-probe.md` canonical pattern.
>
> **Acceptance**:
> 1. Every remote probe wrapped in `bash -lc`.
> 2. SSH flags as in skill doc.
> 3. Compound escalation gate (SSH fail **AND** (claude=0 **OR** orochi absent)).
> 4. Routine all-green: written to `~/.scitex/healer/last-scan.json`, **not** posted.
> 5. Consume `~/.scitex/orochi/fleet-watch/` if head-<host> snapshot is available; fall back to own probe otherwise.
>
> **Done signal**: DM the dispatcher (or one-line post to `#heads` for cross-head visibility): `worker-healer-<host> adoption complete, job <id>`, then mark this row ✅ in `convention-connectivity-probe.md`.

### NAS/storage lane (owner: head-<host>)
> **Task**: Align `worker-healer-<host>` `/loop` with canonical pattern and switch it to **pure consumer** of its own `fleet_watch.sh` output (no duplicate probes).
>
> **Acceptance**:
> 1. Healer reads `~/.scitex/orochi/fleet-watch/*.json` on every tick; no direct `ssh` calls.
> 2. Escalation decisions use the same compound gate as the canonical skill.
> 3. Silent success (no routine posts).
> 4. If the snapshot is older than 2× `fleet_watch` interval, escalate staleness once and stop probing until fresh.
>
> **Done signal**: same as primary workstation lane.

### HPC cluster lane (owner: head-<host>)
> **Task**: Feasibility note for a future `worker-healer-<host>`. No implementation until #283 resolved.
>
> **Acceptance**:
> 1. Document whether a long-lived probe loop can run on login1 (policy: controller-only is OK, see `project_spartan_login_node` memory).
> 2. List which metrics are obtainable on login1 vs require a compute allocation.
> 3. Post a short design note to `#heads` (or DM lead); update this skill's per-host row with link.
>
> **Done signal**: feasibility note posted; skill row updated to 📝 feasibility-complete.

## Related

- `infra-resource-hub.md` — the aggregated snapshot store that consumes probe output
- `fleet-communication-discipline.md` rule #6 — silent success, no routine OK posts
- `agent-health-check.md` — the 8-step health checklist that depends on these probes
- memory `project_spartan_login_node.md` — probe Spartan on login1 only
