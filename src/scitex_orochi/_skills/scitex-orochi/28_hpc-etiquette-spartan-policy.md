---
name: orochi-hpc-etiquette-spartan-policy
description: UniMelb Research Computing canonical Spartan policy — login-node compute allowlist, TCP port policy, batch-only stance, account lifecycle, project expiration, inappropriate-use clauses. Reproduced verbatim from the upstream policy page with fleet implications.
---

# HPC etiquette — UniMelb Spartan canonical policy

> Sub-file of `hpc-etiquette.md`. See the orchestrator for context.

## UniMelb Research Computing canonical policy (Spartan)

This section reproduces the relevant parts of the upstream
UniMelb Research Computing Spartan policies page as the
authoritative text. The fleet's summary rules elsewhere in
this file are paraphrases; when there is any doubt about
what Spartan allows, **the upstream text is the source of
truth**, not the fleet paraphrase.

**Canonical source**:
<https://dashboard.hpc.unimelb.edu.au/policies/>

Captured 2026-04-15 via the operator msg#12411 (relayed to the
fleet in msg#12418 by head-<host> with explicit
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

- `tmux` coordinators for `head-<host>` and healer-style
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

### Spartan is for batch, not web apps (canonical)

> Spartan is designed and optimised for batch jobs (i.e. no
> need for user interaction). As such, it is not really
> designed for applications which require users to connect
> via web interfaces. It may be very difficult or
> impossible to make certain applications work with
> Spartan.
>
> **We will not host web applications which need to be
> always on.** If you require this, please consider using
> the Melbourne Research Cloud.

Fleet implications:

- **Always-on fleet services do not belong on Spartan.**
  The scitex-orochi hub, dashboards, cloudflared tunnels,
  and any other persistent web-exposed service live on
  NAS / primary workstation / Melbourne Research Cloud, not on Spartan.
- HPC head agents and project-specific agents are **ssh-triggered**, not
  always-on. They come up when the operator ssh-es in, do
  their batch work, and exit. The unstick loop is the one
  exception, and it is explicitly bash-only with a tiny
  wall-budget per sweep; it does not expose any port or
  web surface.
- If a future fleet need requires a persistent web service
  that is tied to Spartan data (e.g. a live paper rendering
  service per the operator msg#12289), the service host is
  **Melbourne Research Cloud**, and the service reads
  Spartan data via a scheduled data-movement job, not a
  direct bind.

### Account lifecycle (canonical)

> **Keeping account information up to date**: All users
> must keep their account information up to date, including
> their supervisor, position and department. A valid,
> institutional email address is required. To update your
> information, go to Karaage, and click Personal → Edit
> personal details.
>
> **Locking of user accounts**: User accounts will be
> locked when emails sent receive a bounce message,
> indicating the mailbox does not exist anymore.
>
> **User home directories will be deleted 6 months after
> being locked.**

Fleet implications:

- `the operator` is the fleet's canonical Spartan account
  holder. Keeping `the operator`'s UniMelb institutional email
  live and bounce-free is a load-bearing condition for
  every Spartan agent the fleet operates.
- If `the operator` changes email or the account information
  needs to be updated (supervisor transition, department
  change), the update happens through Karaage (the UniMelb
  account self-service portal), **not** via a support
  ticket to HPC admins. Agents do not touch this.
- **Email bounce → lock → 6-month home-dir delete** is a
  hard timeline. If the operator is away for extended periods,
  the fleet's health-daemon should flag account-inactivity
  risk before the lock threshold is reached.

### Project expiration (canonical)

> **Expiration of the Project**: A project will be
> considered to be expired when there are no valid unlocked
> user accounts left in the project.
>
> As per our Managing Data, you should only keep
> computational data on Spartan. Any critical or not used
> data should be uploaded to Mediaflux or another platform.
>
> With no valid unlocked user accounts left in the project,
> the data in project and scratch is inaccessible to all
> users.
>
> We will delete all project and scratch data for the
> project **6 months after the project has expired**
> according to the above criteria. We will attempt to send
> an email to the project leader 1 week before we delete
> the data.

Fleet implications:

- Shared projects (near-full disk, read-only for some agents)
  are the immediate concern. Renewal is owned by the project
  leader, not by the fleet. The fleet's role is **observation
  only** -- detect if a project expires and alert.
- The operator's own project stays active as long as the
  operator's account does.
- **"Computational data only, move critical stuff to
  Mediaflux"** is the canonical storage-tier advice the
  fleet should honor. Critical paper data (manuscripts,
  final figures, published tables) must live in
  Mediaflux or an equivalent long-term store, not on
  Spartan scratch or project directories.
- **1-week delete warning** is the fleet's last-chance
  window. Any Spartan project the fleet owns or
  collaborates on should have an operator (human or
  fleet-coordinator) watching for the warning email so
  the data is preserved before the delete fires.

### Inappropriate use / service denial (canonical)

> Inappropriate use of the service — If a user engages in
> activity that contravenes the University IT policies,
> standards and guidelines, or the processes described
> here, their access to the service will be suspended,
> pending a review. In the case where the user is also
> the project owner, the project may also be suspended,
> effectively denying access to other project
> participants. If the activity is deemed to be
> malicious, the user and the project may be removed
> from the service.
>
> Damage to the service — If a user misuses the service,
> either wittingly or unwittingly, and causes the
> degrading or denial of service for other users, access
> will be suspended pending a review.

Fleet implications:

- **"Unwittingly" is not a defense.** The 2026-04-14 Sean
  Crosby `find /` incident is the canonical example of
  unwitting damage — the agent did not mean harm, the
  admin still complained, and the fleet is on notice. The
  fleet's compliance posture is **assume every unbounded
  filesystem walk is logged at the storage layer** and
  act accordingly.
- **A single project-owner suspension affects every
  collaborator.** Because the operator is the project owner
  for one project and a collaborator on another, a
  suspension would cascade into the fleet's entire
  NeuroVista and gPAC research pipeline. The blast
  radius of a single bad command is huge.
- **Escalation on first complaint** — if any HPC admin
  contacts the operator about fleet behavior, the fleet
  stops the offending pattern immediately, patches the
  anti-pattern catalog in this file, and drafts the
  apology reply in the same hour. See the "Fleet
  escalation" section below for the full protocol.

See also the canonical UniMelb policy section below — the fleet's own login-node rule is a summary, the canonical source is the authority.

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

### Spartan is for batch, not web apps (canonical)

> Spartan is designed and optimised for batch jobs (i.e. no
> need for user interaction). As such, it is not really
> designed for applications which require users to connect
> via web interfaces. It may be very difficult or
> impossible to make certain applications work with
> Spartan.
>
> **We will not host web applications which need to be
> always on.** If you require this, please consider using
> the Melbourne Research Cloud.

Fleet implications:

- **Always-on fleet services do not belong on Spartan.**
  The scitex-orochi hub, dashboards, cloudflared tunnels,
  and any other persistent web-exposed service live on
  NAS / MBA / Melbourne Research Cloud, not on Spartan.
- `head-spartan` + `proj-ripple-wm-spartan` +
  `neurovista-spartan` etc. are **ssh-triggered**, not
  always-on. They come up when ywatanabe ssh-es in, do
  their batch work, and exit. The unstick loop is the one
  exception, and it is explicitly bash-only with a tiny
  wall-budget per sweep; it does not expose any port or
  web surface.
- If a future fleet need requires a persistent web service
  that is tied to Spartan data (e.g. a live paper rendering
  service per ywatanabe msg#12289), the service host is
  **Melbourne Research Cloud**, and the service reads
  Spartan data via a scheduled data-movement job, not a
  direct bind.

### Account lifecycle (canonical)

> **Keeping account information up to date**: All users
> must keep their account information up to date, including
> their supervisor, position and department. A valid,
> institutional email address is required. To update your
> information, go to Karaage, and click Personal → Edit
> personal details.
>
> **Locking of user accounts**: User accounts will be
> locked when emails sent receive a bounce message,
> indicating the mailbox does not exist anymore.
>
> **User home directories will be deleted 6 months after
> being locked.**

Fleet implications:

- `ywatanabe` is the fleet's canonical Spartan account
  holder. Keeping `ywatanabe`'s UniMelb institutional email
  live and bounce-free is a load-bearing condition for
  every Spartan agent the fleet operates.
- If `ywatanabe` changes email or the account information
  needs to be updated (supervisor transition, department
  change), the update happens through Karaage (the UniMelb
  account self-service portal), **not** via a support
  ticket to HPC admins. Agents do not touch this.
- **Email bounce → lock → 6-month home-dir delete** is a
  hard timeline. If ywatanabe is away for extended periods,
  the fleet's health-daemon should flag account-inactivity
  risk before the lock threshold is reached.

### Project expiration (canonical)

> **Expiration of the Project**: A project will be
> considered to be expired when there are no valid unlocked
> user accounts left in the project.
>
> As per our Managing Data, you should only keep
> computational data on Spartan. Any critical or not used
> data should be uploaded to Mediaflux or another platform.
>
> With no valid unlocked user accounts left in the project,
> the data in project and scratch is inaccessible to all
> users.
>
> We will delete all project and scratch data for the
> project **6 months after the project has expired**
> according to the above criteria. We will attempt to send
> an email to the project leader 1 week before we delete
> the data.

Fleet implications:

- `punim0264` (shared, 9584 GB / 10001 GB, 95% disk, read-
  only for head-spartan per `project_punim0264_expiry.md`
  memory + head-mba msg#11651 fleet awareness) is the
  immediate concern. The renewal is owned by the project
  leader (Pip Karoly, NeuroVista PI), not by the fleet.
  The fleet's role is **observation only** — detect if
  the project expires and alert.
- `punim2354` (ywatanabe-only, 5885 GB / 8002 GB, 73%
  disk, 57% inodes) is ywatanabe's own project and stays
  active as long as the ywatanabe account does.
- **"Computational data only, move critical stuff to
  Mediaflux"** is the canonical storage-tier advice the
  fleet should honor. Critical paper data (manuscripts,
  final figures, published tables) must live in
  Mediaflux or an equivalent long-term store, not on
  Spartan scratch or project directories.
- **1-week delete warning** is the fleet's last-chance
  window. Any Spartan project the fleet owns or
  collaborates on should have an operator (human or
  fleet-coordinator) watching for the warning email so
  the data is preserved before the delete fires.

### Inappropriate use / service denial (canonical)

> Inappropriate use of the service — If a user engages in
> activity that contravenes the University IT policies,
> standards and guidelines, or the processes described
> here, their access to the service will be suspended,
> pending a review. In the case where the user is also
> the project owner, the project may also be suspended,
> effectively denying access to other project
> participants. If the activity is deemed to be
> malicious, the user and the project may be removed
> from the service.
>
> Damage to the service — If a user misuses the service,
> either wittingly or unwittingly, and causes the
> degrading or denial of service for other users, access
> will be suspended pending a review.

Fleet implications:

- **"Unwittingly" is not a defense.** The 2026-04-14 Sean
  Crosby `find /` incident is the canonical example of
  unwitting damage — the agent did not mean harm, the
  admin still complained, and the fleet is on notice. The
  fleet's compliance posture is **assume every unbounded
  filesystem walk is logged at the storage layer** and
  act accordingly.
- **A single project-owner suspension affects every
  collaborator.** Because ywatanabe is the project owner
  for `punim2354` and a collaborator on `punim0264`, a
  suspension would cascade into the fleet's entire
  NeuroVista and gPAC research pipeline. The blast
  radius of a single bad command is huge.
- **Escalation on first complaint** — if any HPC admin
  contacts ywatanabe about fleet behavior, the fleet
  stops the offending pattern immediately, patches the
  anti-pattern catalog in this file, and drafts the
  apology reply in the same hour. See the "Fleet
  escalation" section below for the full protocol.
