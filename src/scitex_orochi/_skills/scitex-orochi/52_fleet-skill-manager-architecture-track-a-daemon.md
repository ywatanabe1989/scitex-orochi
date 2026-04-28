---
name: orochi-skill-manager-architecture-track-a-daemon
description: Track A of the skill-manager hybrid split — `skill-sync-daemon` (process-layer, no LLM, idempotent dual-run on primary host launchd + standby host systemd). Cadence, file layout, miss-backfill semantics. (Split from 52_fleet-skill-manager-architecture-impl.md.)
---

> Sibling: [`71_fleet-skill-manager-architecture-track-b-and-pilots.md`](71_fleet-skill-manager-architecture-track-b-and-pilots.md) for Track B (worker-skill-manager) and parallel pilots.
## Track A — `skill-sync-daemon` (process layer, primary host primary + standby host warm-standby)

A launchd job on primary host (primary) running the same bash/python script
as a systemd user timer on standby host (warm-standby). Pure
bash/python, no Claude session on either host.

### Cadence

- **Default**: every 30 minutes on **both** hosts.
- **No lease election required.** The output is idempotent: same
  input (two shared skill repos at a given HEAD commit) → same
  dotfiles mirror state. If primary host primary runs at `T+0` and writes
  the mirror, standby host standby running at `T+0:30` finds the same
  inputs and writes the same mirror (or an updated mirror if HEAD
  moved during the interval). Both mirrors live on their own host
  and are equivalent because the inputs are canonical. This is
  head-<host> option (d) from msg#11499 — idempotent dual-run, no
  shared lease store required.
- **Adjustable live**: if the skill library churns fast enough
  that 30 min backs up drift, drop to 15 min; if ticks keep
  finding nothing, stretch to 60 min. The cadence knob lives in
  the launchd plist on primary host and the systemd unit on standby host; either
  host's own head can adjust without cross-host coordination.
- **Miss-backfill property**: if primary host primary misses an interval
  (launchd not loaded, host sleeping, etc.), the next standby host tick
  within 30 minutes catches the drift. Worst-case drift window
  is bounded by `max(primary host cadence, standby host cadence)`, not by any
  single host's uptime.

### Per-tick procedure (in order)

1. **Scan the skill locations (public + private):**
   - `~/proj/scitex-agent-container/src/scitex_agent_container/_skills/scitex-agent-container/` (public, canonical)
   - `~/proj/scitex-orochi/src/scitex_orochi/_skills/scitex-orochi/` (public, canonical)
   - `~/.scitex/agent-container/skills/scitex-agent-container-private/` (private per-machine, symlinked on export)
   - `~/.scitex/orochi/skills/scitex-orochi-private/` (private per-machine, symlinked on export)
   - Convention: `~/.scitex/<suffix>/skills/<package>-private/` → `~/.claude/skills/scitex/<package>-private/`
2. **Git status** of the two shared locations. If dirty (uncommitted
   local edits), skip the export step for that repo and log the
   skip — never clobber in-progress work.
3. **Run** `scitex-dev skills export --clean` in each clean repo.
   Verify exit 0. On non-zero: write the full stderr to the log
   and drop a touch-file `~/.scitex/orochi/skill-sync-daemon.fail`
   so the agent layer's healer-prober notices on next probe.
4. **Frontmatter integrity scan.** Verify each `*.md` skill file
   in the two shared trees has a frontmatter block with `name:`
   and `description:` fields. Repair eligibility is **strictly
   limited** (see "Auto-repair threshold" below).
5. **Dedupe candidate detection.** Compare `name:` and
   `description:` across skills in the same tree; flag files whose
   name or description shares ≥3 significant tokens with another
   skill. Log the candidates, do **not** merge — merge is an
   agent-layer decision (Track B worker opens an issue).
6. **Dotfiles mirror sync.** If either shared tree's HEAD commit
   changed since this host's previous tick, rsync the tree into
   `~/.dotfiles/src/.claude/skills/` so new agent hosts inherit
   the update. Use `rsync --delete` within the target subtree to
   keep the mirror exact. **Host-local**: primary host writes to
   `~/.dotfiles/...`, standby host writes to its own
   `~/.dotfiles/...`; both mirrors are equivalent because both
   read from the same canonical upstream repos via `git pull`.
7. **Write one log line** to host-local
   `~/.scitex/orochi/logs/skill-sync-daemon.log` with:
   `ISO8601 | host=<hostname> | tick=N | exported=<N> | drift-repaired=<N> | dedupe-flags=<N> | mirror-updated=<bool> | wall-time=<sec>`
8. **No hub post.** Ever. State-change-only reporting is the
   agent layer's job (Track B worker reads the log via host-local
   file access on primary host, or via SSH on standby host, when asked).

### Why primary host primary, standby host warm-standby

1. **Empirical stability** (the operator msg#11464) — primary host is
   currently the most stable agent host, and the skill-sync pilot
   benefits from the least-risky landing pad.
2. **standby host SLURM traffic is real** (head-<host> msg#11492/#11493) —
   `scitex-cloud` visitor sessions run 6 concurrent SLURM jobs
   (12/12 CPU, 24GB allocated, 59-min walltime caps,
   `scitex-alloc-<hash>.sh` allocation scripts). A CPU-hot direct-
   exec systemd timer on standby host would step on visitor allocations via
   the kernel scheduler even without going through SLURM.
   `scitex-dev skills export --clean` is fast but non-trivial; it
   should not be a first-class primary host→standby host offload target.
3. **standby host is the right warm-standby** because it's 24/7 on and
   systemd-native. The standby's cost is one idempotent bash
   script per 30 minutes — I/O-light and CPU-cheap, which is
   exactly what the "standby host accepts" column of the daemon host
   policy table (`00-agent-types.md`) calls out as fine.
4. **Escape hatch**: if a future heavy-compute phase is needed
   (e.g. bulk embedding over all skills, semantic deduplication),
   submit as `sbatch` on standby host rather than direct systemd-timer
   exec. standby host's SLURM queue alongside visitor traffic is the right
   path, not a direct launchd-style CPU burst.

### Auto-repair threshold (per head-<host> review, msg#11427)

The daemon is **only** allowed to auto-repair frontmatter issues
that are mechanical, reversible, and carry zero semantic risk:

- Fix frontmatter typos in field names (`descrption:` →
  `description:`).
- Align `name:` to filename when the mismatch is obviously a
  rename that forgot to update the field.
- Normalize whitespace / trailing newlines in the frontmatter
  block.

The daemon **must not** auto-edit:

- The `description:` body text, or any other free-text field.
- The markdown body of the skill.
- Trigger rules, deliverables, cadences, or any other
  semantics-bearing content.

Anything outside the auto-repair whitelist → log the finding and
open a `gh issue` under label `skill-drift` tagged
`@worker-skill-manager-<host>`. The agent-layer worker reviews those
issues on demand.

### Failure handling

- Non-zero exit from `scitex-dev skills export`: drop
  host-local `~/.scitex/orochi/skill-sync-daemon.fail` touch-file,
  include full stderr in the log, continue the rest of the tick.
  Do **not** retry — an agent-layer worker should look at it.
- Rsync failure: same pattern. Don't self-recover.
- Filesystem scan error: log, skip the affected path, continue.

Each host owns its own `.fail` touch-file in its own
`~/.scitex/orochi/` so failures on one host don't block the
other. The Track B worker on primary host reads the local `.fail`
directly and reads standby host's via SSH (or via a hub `fleet_report`
endpoint if/when the daemon inventory gets aggregated centrally).

The daemon never escalates. The healer-prober notices the
`.fail` touch-file or the stale log timestamp on its next probe
and spins up an agent-layer worker to triage.

