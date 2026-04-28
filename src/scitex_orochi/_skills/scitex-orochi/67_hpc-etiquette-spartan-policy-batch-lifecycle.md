---
name: orochi-hpc-etiquette-spartan-policy-batch-lifecycle
description: Spartan canonical policy — batch-only stance + account lifecycle + project expiration + inappropriate-use. (Split from 17_hpc-etiquette-spartan-account-lifecycle.md.)
---

> Sibling: [`17_hpc-etiquette-spartan-policy-login-ports.md`](17_hpc-etiquette-spartan-policy-login-ports.md) for login + TCP port.

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
