---
name: orochi-hpc-etiquette-general
description: General HPC cluster etiquette — login nodes, schedulers, filesystems, modules, network, and absolute rules (never find /, never compute on login nodes, etc.). Sub-file of hpc-etiquette.md.
---

# HPC etiquette — general rules

> Sub-file of `hpc-etiquette.md`. See the orchestrator for context and the
> Spartan-specific canonical policy + guardrails sub-files.

# HPC etiquette

Shared HPC filesystems have hundreds of millions of files and are watched by admins who can and will revoke access. A single agent scripting `find / -name X` across `/data/gpfs` hits the filesystem as hard as any real workload and is indistinguishable from a denial-of-service from the storage layer's perspective.

This skill is the fleet's rulebook for being a good HPC guest, written specifically after the 2026-04-14 incident where Sean Crosby (Head of Research Computing Infrastructure, UniMelb) emailed the operator to stop running `find / -name pdflatex` on Spartan (msg #10971). That `find` was started by an agent trying to locate a binary — the kind of operation that is free on a laptop and catastrophic on a shared cluster.

## Continued in

- [`60_hpc-etiquette-general-extras.md`](60_hpc-etiquette-general-extras.md)
