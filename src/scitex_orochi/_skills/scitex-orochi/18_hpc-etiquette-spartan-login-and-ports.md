---
name: orochi-hpc-etiquette-spartan-login-and-ports
description: UniMelb Spartan policy — login-node compute allowlist + TCP port policy. Reproduced verbatim with fleet implications. (Split from 18_hpc-etiquette-spartan-fleet-implications.md.)
---

> Sibling: [`68_hpc-etiquette-spartan-batch-and-lifecycle.md`](68_hpc-etiquette-spartan-batch-and-lifecycle.md) for batch/web-apps stance, account lifecycle, project expiration, inappropriate-use clauses.
## UniMelb Research Computing canonical policy (Spartan)

This section reproduces the relevant parts of the upstream
UniMelb Research Computing Spartan policies page as the
authoritative text. The fleet's summary rules elsewhere in
this file are paraphrases; when there is any doubt about
what Spartan allows, **the upstream text is the source of
truth**, not the fleet paraphrase.

**Canonical source**:
<https://dashboard.hpc.unimelb.edu.au/policies/>

Captured 2026-04-15 via ywatanabe msg#12411 (relayed to the
fleet in msg#12418 by head-ywata-note-win with explicit
directive to fold into this skill) and msg#12414 link drop.
Re-fetch the canonical page whenever there is a policy
question — upstream is allowed to change without notifying
the fleet.

### Login-node compute allowlist (canonical)

> No applications other than code editors (`vim`, `emacs`),
> data moving applications (e.g. `rsync`,
> `unimelb-mf-clients`) and Python / R package installations
> (e.g. `pip install`, `install.packages()`) can be run on
> the login nodes. **Applications using CPU or memory will
> be killed when run on the login nodes.**

> For code editors which connect externally, such as
> **VSCode**, **do not run code on Spartan through those
> external code editors** (e.g. running Python code on the
> login nodes).

Fleet implications:

- `tmux` coordinators for `head-spartan` and healer-style
  agents are OK on login1 because they are not compute
  workloads — they are bash-level state machines. The
  `cgroup nproc=1` limit is the enforcement that will kill
  anything that crosses the "compute" line.
- **VSCode remote-execution is forbidden.** Even if the
  VSCode extension itself is lightweight, it will run Python
  kernels / tests / linter subprocesses on the login node
  which is exactly the banned case. If you need an IDE, use
  Open OnDemand's hosted JupyterLab on a compute node, not
  remote VSCode against login1.
- Heavy wheel installations (`pip install torch`, etc.) are
  banned because compilation + disk I/O on login1 competes
  with everyone else's ssh session. Do them inside an
  `srun` / `sbatch` session.

### TCP port policy (canonical)

> Some popular applications (such as Jupyter, RStudio,
> wandb) require TCP ports to be opened during the running
> of the application.
>
> - **No ports are externally accessible on either the
>   login nodes or compute nodes.**
> - **Do not run applications opening TCP ports on the
>   login nodes.**
> - As Spartan is a shared resource, you cannot guarantee
>   that a port you want to use won't be already in use by
>   other users on the worker node you are using. You
>   should check to see if the port is available before you
>   try to use it. If you try to open a port that someone
>   else is using, your job will most likely fail.
>   Example script: `/apps/examples/TCP_Ports` on Spartan.
> - **If you can access a port, so can everyone else on the
>   platform.** That means that others would be able to
>   connect and access the data available through the port
>   you open. **Make sure you secure the application using
>   the port with a username/password.**
> - **Try not to use popular ports or ports you don't have
>   access to** (< 1024, 8080, 8888).
> - If an application is available as part of **Open
>   OnDemand**, please run it there in preference to other
>   ways of running it.

Fleet implications:

- **No inbound tunnels on login1.** The cross-host bastion
  mesh (`orochi-bastion-mesh.md`) keeps Spartan-side
  listeners inside `sbatch` jobs, not on login1.
- **No Jupyter / RStudio / wandb servers on login1.** These
  must run inside an `sbatch` allocation on a compute node
  (and even there, bind to localhost + port collision
  check + HTTP auth).
- **Port collision check before `listen`**: every fleet
  agent that opens a TCP port on Spartan should first check
  `ss -ltn` or equivalent to confirm the port is free. The
  upstream example script at `/apps/examples/TCP_Ports`
  shows the canonical pattern.
- **Prefer Open OnDemand** (`https://dashboard.hpc.unimelb.edu.au/`)
  for any UI app the fleet needs. Running Jupyter through
  OOD is the fleet's default, not running Jupyter manually
  via `ssh -L`.
- **Popular ports are banned**: < 1024 is privileged,
  8080 + 8888 are the "I'll just use the default"
  favorites that collide immediately. Pick a random
  high port (10000–65535) and document it per-job.

