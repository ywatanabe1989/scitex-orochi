---
name: orochi-spartan-dashboard
description: Authoritative source for Spartan (UniMelb HPC) account status, quotas, and job history — https://dashboard.hpc.unimelb.edu.au/. Agents should consult the dashboard (or admin-approved CLI) before taking any compute / storage decision, never probe filesystems directly.
scope: fleet-internal
---

# Spartan dashboard

**URL**: https://dashboard.hpc.unimelb.edu.au/

Operated by UniMelb Research Computing Services. Requires university SSO login. Shared by ywatanabe 2026-04-14 (msg #10984) immediately after the Sean Crosby `find /` complaint (msg #10971) — the dashboard is the **canonical** place to answer questions about Spartan state without touching the filesystem.

## What the dashboard gives you

The dashboard surfaces, through UniMelb's own admin interface, the information that agents otherwise used `find`, `du`, `squeue`, and `sacct` to piece together. Treat the dashboard as the source-of-truth for each of these categories:

| Question | Dashboard answer | Anti-pattern to avoid |
|---|---|---|
| "How much disk am I using under `/data/gpfs/projects/<punim>`?" | Project Storage page | `du -sh /data/gpfs/...` |
| "How many inodes left under `/home/ywatanabe`?" | Home Quota page | `find ~/ \| wc -l` |
| "What's my current job queue status?" | Jobs / My Jobs | `squeue -u ywatanabe` tight-loop polling |
| "Which partitions have idle GPUs right now?" | Partitions / GPU Status | `sinfo` polling every 10 s |
| "How much SU / compute time have I used this month?" | Usage Reports / Accounting | `sacct` wide date range scans |
| "Which projects am I charging against?" | Account / Projects | `sacctmgr show assoc user=$USER` |
| "Have I had any failed jobs this week?" | Job History + filter by state=FAILED | `sacct -S YYYY-MM-DD --state FAILED` |

When an agent needs any of this data and the dashboard would answer it, **the dashboard is the correct path** — lower filesystem load, admin-blessed interface, cached queries.

## Why it matters right now

The 2026-04-14 Sean Crosby email (see `hpc-etiquette.md` + rule #16 in `fleet-communication-discipline.md`) made clear that unbounded filesystem walks on Spartan draw admin attention and can cost the fleet its access. The dashboard exists precisely so that users can answer "how full is my quota", "what's happening with my jobs", and "where am I in the queue" without running `find /` or `du -sh /data` — the exact commands that triggered the complaint.

Agents that want to make a compute / storage decision must prefer, in order:

1. **Dashboard page** (if reachable via a prior captured human session or a scripted login with credentials).
2. **Narrow CLI on the login node** scoped to a single known path: `du -sh ~/proj/neurovista`, `squeue -u $USER -j <jobid>`, `sacct -j <jobid> --format ...`.
3. **`sacctmgr show assoc user=$USER format=...`** for accounting state.
4. **Ask ywatanabe** if none of the above surface the answer and the decision is time-sensitive.

What agents must **not** do: fall back to `find /`, `du /`, `ls -R`, or any unbounded traversal when the dashboard would have answered the question. That anti-pattern is now banned by rule #16.

## Authentication

The dashboard uses UniMelb SSO. Automated agent access is not currently wired — fleet agents cannot log into the dashboard from cron. The practical model is:

- ywatanabe opens the dashboard in a browser when needed.
- Screenshots or CSV exports are shared via Orochi `#ywatanabe` channel if an agent needs the content.
- For structured queries an agent can run in script form, the **narrow CLI** path above is the fallback.

If a future automation use case justifies it, a service token / API key can be requested from the HPC help desk; do not attempt to scrape the SSO flow from agent code.

## Sean Crosby's explicit ask

From the 2026-04-14 email thread (msg #10971):

> *"Please stop doing that. It causes unnecessary stress on all the filesystems, and we have 100s of millions of files. What file are you looking for, and why are you using find to try to get the location of it?"*

The dashboard is the fleet's long-term answer to that question: if an agent thinks it needs to "find" something on Spartan, it should (a) articulate what it is looking for, (b) check whether the dashboard already exposes it, (c) fall back to the narrow CLI if not, (d) never use unbounded `find`.

## Related

- `hpc-etiquette.md` — the full ban on `find /` and the preventive-measures rulebook
- `fleet-communication-discipline.md` rule #16 — HPC filesystem etiquette
- `spartan-hpc-startup-pattern.md` — Lmod chain, LD path, login-vs-compute policy
- memory `project_spartan_login_node.md` — login1 controller-only rule
- email thread with Sean Crosby, 2026-04-14 (relayed via Orochi msg #10971)

## Change log

- **2026-04-14 (initial)**: Added immediately after ywatanabe msg #10984 shared the dashboard URL as the canonical Spartan state source in response to the same-day Sean Crosby `find /` complaint. Kept short as requested. Author: mamba-skill-manager (knowledge-manager lane).
