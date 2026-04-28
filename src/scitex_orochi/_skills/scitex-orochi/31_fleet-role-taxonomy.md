---
name: orochi-fleet-role-taxonomy
description: Orochi fleet taxonomy — 2-layer (process/agent) + 4 exclusive roles (lead / head / worker / daemon) + orthogonal function tags. Defining axis is "LLM-in-loop?". Daemons are quota-zero programmatic processes, not agents. Host-diverse daemon policy (not NAS-exclusive) because NAS is production-loaded with scitex-cloud visitor SLURM. Ratified 2026-04-14 msg#11475.
---

# Fleet Role Taxonomy

Before 2026-04-14 the `mamba-` prefix was an overloaded bag. Nobody
could tell at a glance what any `mamba-*` agent actually *did*, and
the fleet was quietly paying Claude quota for work that had zero
LLM judgment in it. This skill fixes both problems at once, and —
after the NAS-stability / SLURM-load correction arc later the same
day — fixes them in a **host-diverse** way so that the daemon layer
does not collapse onto a single host.

## Origin

*(Message IDs in this section are approximate — the thread moved
fast and voice-transcription artifacts mean some IDs are ±1 from
the true landing order. The shape of the argument is the
authoritative record, not the exact IDs.)*

### Phase 1 — taxonomy convergence

- 2026-04-14 msg #11414 — ywatanabe: "mamba に色んな意味が出てきた、
  カテゴライズが必要".
- msg #11420 — head-mba first draft: 5 categories
  (head / dispatcher / daemon / prober / worker).
- msg #11422 — ywatanabe locks vocab to
  lead / head / worker / daemon / prober.
- msg #11428 — ywatanabe's key insight: **"programmatic なのは
  もうエージェントじゃないので daemon、agentic なのが worker"**.
  This is the axis everything else falls out of.
- msg #11430 — head-nas: promotes ywatanabe's insight to the
  defining axis → daemon = non-agentic loop, worker = LLM-backed.
  `prober` demoted to function tag (same "probe" function can be
  agentic or programmatic depending on implementation).
- msg #11436 — head-mba: role × function orthogonality.
- msg #11440 — head-mba: 2-layer structure (process layer + agent
  layer), daemon lives in the process layer, not the agent layer
  at all.
- msg #11439, #11446 — mamba-todo-manager confirms the same hybrid
  shape (Track A programmatic / Track B agentic) applies beyond
  skill-manager.
- msg #11448 — head-mba asks ywatanabe for final GO on PoC.

### Phase 2 — NAS stability + host-diverse pivot

- msg #11464 — ywatanabe flags naming ambiguity and empirical
  host-stability differences; MBA currently the most stable host.
- msg #11468, #11481 — pivot begins: "NAS as exclusive daemon
  host" is too simple because NAS is running real production
  traffic.
- msg #11483 — ywatanabe proposes a `metrics-collector` /
  `host-self-describe` daemon family for OS / hardware / tunnel /
  docker / SLURM state, landing on every host.
- msg #11484, #11487 — ywatanabe: WSL also runs SLURM, so SLURM
  is not Spartan-exclusive; daemon policy must reason about SLURM
  availability per host.
- msg #11492, #11493, #11502 — head-nas empirical report: NAS has
  6 × `scitex_visitor-*_dotfiles` SLURM jobs running, 12/12 CPUs +
  24GB allocated, 59-min walltime caps, `scitex-alloc-<hash>.sh`
  allocation scripts, visitor sandboxes live. It is **not** dev
  noise. A CPU-hot direct-exec systemd daemon on NAS would step
  on visitor allocations via the kernel scheduler even without
  going through SLURM.
- msg #11499 — head-nas: offers idempotent dual-run pattern for
  the skill-sync pilot (MBA primary, NAS warm-standby, no shared
  lease required because the output is idempotent).
- msg #11501 — head-mba: correction on
  `autossh-tunnel-1230.service` — it's a reverse SSH tunnel from
  NAS → MBA bastion (port 1230 on MBA exposes NAS:22), not a
  WSL↔NAS link.
- msg #11475 — ywatanabe's "final check before GO" turn, the
  ratification point for the 2-layer + host-diverse model this
  file encodes.

## The defining axis

> **Does the loop require LLM judgment to make its next decision?**

- **No** → it's a programmatic loop. It belongs in the *process
  layer*. It consumes zero Claude quota. It has no `.claude/`
  session. It's a `daemon`.
- **Yes** → it's an agent. It belongs in the *agent layer*. It
  holds a Claude session, consumes quota, and is one of
  `lead` / `head` / `worker` depending on what it talks to.

This is the only axis that matters. Everything else is
nomenclature for "what role does this agent play inside the agent
layer" or "what function does this daemon/agent performs".

**Quota economics is load-bearing** (ywatanabe #11403, #11407):
both the 5-hour and the weekly Claude quota ceilings are live
constraints, not polish. Daemon migration is *quota relief*. Every
hour a Claude session sits in a deterministic loop is an hour of
ceiling headroom the fleet doesn't have for real agentic work. The
split is not aesthetic; it is the only way to keep the agent layer
alive under current quota pressure.

## Continued in

- [`19_fleet-role-taxonomy-layers.md`](19_fleet-role-taxonomy-layers.md)
- [`45_fleet-role-taxonomy-tags-and-roster.md`](45_fleet-role-taxonomy-tags-and-roster.md)
