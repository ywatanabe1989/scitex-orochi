---
name: orochi-hpc-etiquette
description: How to be a good citizen on shared HPC clusters — any site, Spartan or otherwise. Orchestrator linking the general / Spartan-canonical-policy / guardrails sub-files. Response to the 2026-04-14 Sean Crosby (UniMelb HPC admin) complaint about unbounded find.
scope: fleet-internal
---

# HPC etiquette

Shared HPC filesystems have hundreds of millions of files and are watched by admins who can and will revoke access. A single agent scripting `find / -name X` across `/data/gpfs` hits the filesystem as hard as any real workload and is indistinguishable from a denial-of-service from the storage layer's perspective.

This skill is the fleet's rulebook for being a good HPC guest, written specifically after the 2026-04-14 incident where Sean Crosby (Head of Research Computing Infrastructure, UniMelb) emailed the operator to stop running `find / -name pdflatex` on Spartan (msg #10971). That `find` was started by an agent trying to locate a binary — the kind of operation that is free on a laptop and catastrophic on a shared cluster.

This file was split for the 512-line markdown limit. Content lives in
three focused sub-files; this orchestrator is the entry point.

## Sub-files

- [hpc-etiquette-general](hpc-etiquette-general.md) — General rules
  applicable to **every** HPC site (Spartan, NCI, Pawsey, etc.):
  compute/jobs, filesystems/metadata, modules/environment,
  network/SSH, process/billing hygiene, documentation/first-contact;
  the **absolute rules** (never `find /`, never compute on login
  nodes, never `rsync -r ~/`); binary-location cascade; scoping;
  inode-aware operations; SLURM etiquette; login-node policy.
- [hpc-etiquette-spartan-policy](hpc-etiquette-spartan-policy.md) —
  UniMelb Research Computing canonical policy reproduced from
  <https://dashboard.hpc.unimelb.edu.au/policies/>: login-node
  compute allowlist, TCP port policy, "Spartan is for batch not web
  apps", account lifecycle, project expiration, inappropriate-use
  clauses. Each section has fleet implications.
- [hpc-etiquette-guardrails](hpc-etiquette-guardrails.md) — Network
  etiquette, storage hygiene, shell-level guardrails (`find` / `du`
  refusal wrappers), 2026-04-14 incident anti-patterns + correct
  refactor, fleet escalation protocol, related skills, change log.

## Quick reference (defensive rules of thumb)

- Path starts with `/`, `/data`, `/scratch`, `/home` without a specific subpath? → unsafe.
- Scans more than ~10k files? → unsafe.
- Runs more than 60 s on a login node? → unsafe; move to `sbatch`.
- Polls a shared scheduler/db faster than 60 s? → unsafe; cache.
- Would Sean Crosby email the operator if he saw it in `ps -ef`? → if yes, don't run it.

The last one is the canonical test.
