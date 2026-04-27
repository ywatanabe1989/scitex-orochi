# scitex-orochi — Enhancement ideas distilled from the v02→v03 audit cycle

This memo collects forward-looking improvements that emerged from the
audit cycle that closed today (v0.15.5 → v0.15.9). Each is grounded in
a *pattern* observed in the audit, not a one-off symptom — the goal is
to prevent re-occurrence, not to chase the last 5% of the same bug.

Ranked by **leverage** (impact-per-effort).

---

## High leverage

### 1. Pre-commit harness that mirrors `make lint-css` for other "preconditions"

**Pattern observed.** Two of this session's bugs were *property
preconditions silently broken by an unrelated rule*:

- `vertical-align: middle` requires `display: table-cell` —
  `.avatar-clickable { display: inline-flex }` knocked it out.
- `position: absolute; top: 100%` requires a positioned ancestor —
  `.sidebar-brand-compact { position: static }` made the workspace
  dropdown render at viewport bottom.

Both classes are *write-time* errors that no test catches: the rule
parses, the file deploys, the runtime doesn't error, the user sees
"nothing happens." The lint script I just added catches one shape; the
same audit pattern generalizes.

**Idea.** Extend `lint-css-cascade-traps.py` into a small "CSS
preconditions" linter:

| Property | Required ancestor / sibling / display | Audit query |
| --- | --- | --- |
| `vertical-align: middle` | element is `display: table-cell` or inline | (already covered) |
| `top|right|bottom|left|z-index` (with `position: absolute`) | nearest ancestor has `position: relative|absolute|fixed|sticky` | scan template tree, walk DOM ancestors |
| `align-items|justify-content` | parent element has `display: flex` or `grid` | static can't always know parent; warn when seen on a `:not(.flex-container)` selector |
| `gap` (outside flex/grid) | parent is `display: flex|grid|inline-flex|inline-grid` | same as above |
| `position: sticky` | parent has `overflow: visible` (or unset) | grep ancestors for `overflow: hidden\|auto\|scroll` |

Each rule is 20–40 lines of Python. `make lint-css` becomes the
single gate. Effort: 1–2 hours total.

**Why high leverage:** every shipped CSS bug in this audit was a
precondition violation; a single check would have caught both.

---

### 2. Heartbeat schema versioning + backward-compat shim

**Pattern observed.** The session added a new heartbeat field
(`orochi_env_file`) that producers (agents) and the consumer (hub)
have to agree on. The agents are pip-installed across many hosts and
will not all upgrade at once; for now the field works because absent
keys default to empty string, but **there is no central record of
which heartbeat schema version each side speaks**.

Consequence: when we add a non-string-defaultable field next time
(e.g. a structured `orochi_pane_state_v3`), we'll have a silent
window where old agents push v2, hub expects v3, and the dashboard
shows blanks for old fleets.

**Idea.** Introduce `orochi_heartbeat_schema_version` as a top-level
heartbeat field (integer). Hub sets:

- N+1 fields permitted but ignored without warning
- N (current) accepted normally
- N-2 or older returns a 409 with "agent too old, please pip install -U"

Producer side: a `HEARTBEAT_SCHEMA = N` constant in
`scripts/client/_collect_agent_metadata/_collect.py`. Bump per release
when wire shape changes.

**Why high leverage:** retroactively makes every prefix-migration we've
done observable. Effort: 2–3 hours.

---

### 3. Bring agent-fleet `pip` upgrade into a `make` target

**Pattern observed.** `detect-secrets>=1.5` was added as a producer
dep this session for the .env redaction rewrite. *Until the fleet
agents pip-install -U*, they keep running the old (less safe)
redaction. The rollout depends on operator memory.

**Idea.** `make fleet-agents-upgrade` that:

1. SSHs every host listed in `orochi-machines.yaml`.
2. Runs `pip install -U scitex-orochi[agents]` in each agent's venv.
3. Prints per-host before/after `scitex-orochi --version` so we can
   see the fleet line up.
4. Optionally restarts the heartbeat loop so the new collector picks
   up immediately.

Pairs with #2 above: after the upgrade, all agents push the same
heartbeat schema version, eliminating mixed-fleet drift.

**Effort:** 1 hour. Most of the SSH plumbing already exists in
`deployment/fleet/`.

---

### 4. PR-rebase-bot for the 10 PRs we kept open

**Pattern observed.** The PR sweep closed 10/20 stale PRs as
already-superseded. The other 10 were kept open with a rebase-request
comment. Without a forcing function those will rot again — same shape
as the dead-`.js` files that had accumulated for weeks.

**Idea.** A nightly GitHub Action (or local cron via the orochi-cron
infra that already exists in the repo) that:

1. For every PR with `updatedAt > 3 days ago` AND **not** the
   `keep-open` label, comment "auto-stale: closing in 1 day unless
   you push or label `keep-open`".
2. After 1 more day with no activity, close with the same template
   message we used today.
3. Push or non-bot comment auto-removes the `stale` label
   (`remove-stale-when-updated: true`) so a re-pushed PR is
   immediately back in good standing.

**Threshold rationale (2026-04-28):** the operator runs a high-cadence
fleet — 3 days of silence on a PR strongly indicates either it's
landed differently on develop or the author has moved on. Forcing the
re-engagement (push, label, or accept the close) keeps the open-PR
list a *signal* rather than a graveyard.

**Implemented:** `.github/workflows/pr-stale-sweep.yml`
(`actions/stale@v9`, cron `0 12 * * *` UTC, `workflow_dispatch:`
manual trigger).

**Effort:** half day. Provides ongoing branch hygiene without a
manual sweep every quarter.

---

## Medium leverage

### 5. Make the `infra-hub-stability.md` chain into a runbook with health probes

**Pattern observed.** The colima VM-suspension fix was diagnosed by
correlating four independent signals (curl flap pattern, lsof on
:8559, lima ha.stderr.log time-sync events, cloudflared metrics).
Today those signals are documented in prose; next time the same shape
happens (different macOS version, different vmType, …) the diagnosis
restarts from scratch.

**Idea.** A `scripts/server/diagnose-hub-flap.sh` that runs all four
probes in 30 s and prints a verdict:

- "Origin OK, edge healthy → not a hub-side problem"
- "Origin slow on loopback (>1 s) — colima SSH-MUX flap, suspect VM
  suspension, run `tail ~/.colima/_lima/colima/ha.stderr.log | grep
  Time sync`"
- "Cloudflared total_requests=0 — wrong tunnel active, see
  deployment/README.md §Cloudflare tunnels"
- "Daphne logs show errors — hub bug, not infra"

Wire to `make diagnose-hub` so anyone (or any agent) can run it.

**Why medium:** the next operator (or me-on-future-session) saves the
diagnostic chain re-derivation. Effort: 1–2 hours.

---

### 6. Bundle-size budget + Vite manifest checked into git

**Observed.** Bundle is 771 kB / 176 kB gzipped, no lower bound
declared. A single accidental wholesale import (`import * from a/b`)
could double it without anyone noticing on the next deploy.

**Idea.** Add `package.json` `"size-limit"` config (or hand-roll: a
shell check that `du -k hub/static/hub/dist/orochi-*.js` is < 850 kB
ungzipped, < 200 kB gzipped) and wire to the Vite build step. CI
fails when the budget is exceeded; the fix is either to genuinely
reduce or to bump the budget with a comment explaining why.

**Why medium:** prevents silent bloat. Effort: 30 min.

---

### 7. Single-source-of-truth for agent fields (typed schema)

**Observed.** The heartbeat field set is duplicated across:

- `scripts/client/_collect_agent_metadata/_collect.py` (producer)
- `src/scitex_orochi/_cli/commands/heartbeat_cmd.py` (forwarding)
- `hub/views/api/_agents_register.py` (server reception)
- `hub/registry/_register.py` (storage)
- `hub/views/agent_detail.py` (rendering)
- `hub/frontend/src/agents-tab/{overview,detail}.ts` (UI)

Adding a new field today requires touching all six places, with no
type checking that they agree. The recent `orochi_env_file` and
`sac_a2a_*` migrations were each ~6-file diffs.

**Idea.** Define the heartbeat shape once in
`src/scitex_orochi/heartbeat_schema.py` as a Pydantic model (or
TypedDict). Generate the TS interface for the frontend from it via
`pydantic2ts` or hand-converted constant. Linter rule: every field
read from a heartbeat goes through the typed model.

**Why medium:** reduces the cost of the next prefix migration from
6-file diff to 1-file diff. Effort: half-day initial, then linear
savings.

---

## Lower leverage / nice-to-have

### 8. Move test fixtures to factory-boy

`hub/tests/views/api/test_agents_register.py` builds a fresh Workspace
+ WorkspaceToken in every test. Factory-boy would shrink each test by
3–4 lines and improve readability. Cosmetic.

### 9. Auto-purge Cloudflare cache on every Tier-1 hot-cp

I purge manually via curl + the CF API after every deploy. A
`Makefile` target `make prod-cf-purge` already exists; it's not
chained from the hot-cp recipe (because there is no hot-cp recipe —
it's all manual `cat | ssh mba docker exec -i …`). A real
`make prod-hot-cp FILE=…` target that does the cp + collectstatic +
CF purge would be 10 minutes and remove a per-deploy step.

### 10. Status badges in the README

Top-level README has no CI badge, no PyPI version, no test count, no
"last release" badge. Adding the standard set is 5 lines and improves
discoverability for anyone landing on the GitHub repo.

---

## Cross-cutting principle (for the lessons file)

The audit cycle taught one thing very loudly:

> **Make the silent-defeat surfaces observable.** Every bug in this
> session was either a CSS precondition silently disabled, a producer
> shipping data the consumer ignored, a deploy artifact that wasn't
> the one running, or a stale PR that nobody noticed had been
> superseded. The fixes were trivial; finding them was the cost.

Each enhancement above is, in its own way, a way to make a
silent-defeat surface noisy: lint catches preconditions at write time,
schema versioning catches producer-consumer drift at deploy time,
fleet-upgrade catches mixed-version drift, the CF-purge target
catches stale-cache, the diagnose-hub script catches infra flaps in
30 s instead of an hour. The investment per item is small, the leak
they each plug is large.

Pick the top 1–2 by leverage; defer the rest to the next quality
window.
