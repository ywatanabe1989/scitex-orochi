# heal-the-healer

**Audience:** `mamba-healer-mba` (primary); all head-* agents (for hierarchical fallback).
**Status:** Codified 2026-04-13 from the "head-spartan died silently, ywatanabe noticed before healer" incident and the Phase A rolling restart lessons.

## Why this exists

On 2026-04-12, `head-spartan` died mid-session. The MBA-local healer scan did not catch it because healer was only probing MBA tmux sessions. ywatanabe flagged the death directly in `#ywatanabe` after several minutes of silence. The fleet then needed a manual cross-host resurrect via `head-mba`.

This skill exists so the healer never relies on a single host's ps table and so resurrect procedures are codified and shareable.

## The three responsibilities

### 1. Cross-host probe (not MBA-only)

On every health-scan tick, probe **every fleet host** — not just the local one. The authoritative liveness signal is:

1. `ssh <host> "tmux has-session -t <agent-name>"` (exit 0 = session alive)
2. `ssh <host> "pgrep -af 'claude.*<agent-name>'"` (≥ 1 match = claude process alive)
3. `mcp__scitex-orochi__status` heartbeat freshness (via hub registry)

All three must agree, or the agent is in a suspect state. One-out-of-three is enough to trigger a follow-up probe one cycle later; two cycles of mismatch → resurrect.

Host list lives in the shared skill `fleet-members.md`. Do NOT hard-code in healer code — read it at probe time.

### 2. Resurrect without asking

For an agent that has been confirmed dead for two consecutive cycles:

```bash
# Per-host resurrect template
ssh <host> bash -lc '
  cd ~/.scitex/orochi/workspaces/<agent-name> &&
  tmux kill-session -t <agent-name> 2>/dev/null || true &&
  tmux new-session -d -s <agent-name> \
    "claude --model opus[1m] --dangerously-skip-permissions --session continue-or-new"
'
```

Do not ask ywatanabe for permission. Post-hoc reporting (see the feedback memory of the same name): just do, then report to `#agent` with the before/after state.

**Exception — interactive auth required.** If the new `claude` process lands on `/login`, follow the `account-switch-login-protocol` project memory: copy the OAuth URL, post to `#ywatanabe`, wait for the code, inject it. Do not invent a workaround.

### 3. Escalate only when resurrect fails twice

Post to `#escalation` (NOT `#ywatanabe` first) after two failed resurrect attempts. Include:

- Host + agent name
- Which of the three probes failed
- Resurrect command output (last 20 lines, no secrets)
- Suggested manual action (ssh line the user can copy-paste)

The goal is that the escalation message is self-contained enough that any head-* agent or ywatanabe can act on it in one step.

## Rate limits and cadence

- **Probe cadence:** every 5 minutes when fleet is active, every 15 minutes during quiet periods. Don't poll faster — SSH fanout costs add up and can trip the ulimit wall (see todo#254 for the open ulimit-fanout bug).
- **Escalate cadence:** one alert per agent per 30-minute window. Silence duplicate alerts for the same `(host, agent)` tuple during that window.
- **Resurrect cadence:** minimum 2 minutes between resurrect attempts for the same agent. Prevents restart thrash.

## Hierarchy of responsibility

```
head-<host>  →  local resurrect for agents on its own host
mamba-healer-mba  →  cross-host authoritative scan, coordinates head-* resurrect
ywatanabe  →  only when escalation is triggered (double-failure)
```

If a head-* agent is itself dead, the healer's resurrect target is the `head-*` first, then any agents that were depending on it. Never let a single head-* death cascade into a whole-host blackout.

## Known failure modes

1. **SSH connection refused under ulimit wall (todo#254):** probes fall back to a cached state and flag the host as "unknown, not confirmed dead". Do NOT auto-resurrect on unknown state — resurrect requires confirmed dead.
2. **`screen-alive` health method name is misleading:** it checks tmux, not GNU screen (verified 2026-04-12). Do not add a `screen` probe path for agents whose yaml lists `method: screen-alive`.
3. **Workspace cwd bugs:** newly started `claude` processes sometimes land in the wrong cwd (observed for head-spartan). The resurrect template above uses `cd ~/.scitex/orochi/workspaces/<agent-name>` explicitly to prevent this.
4. **Interactive auth on first connect:** `claude` may prompt for OAuth login. See the `account-switch-login-protocol` memory — inject the code, do not abandon the resurrect.

## What the healer must NOT do

- ❌ Probe MBA-only. Fleet is multi-host; single-host probes miss real deaths.
- ❌ Wait for ywatanabe to notice. By the time a human notices, the agent has been dead for minutes and work has been lost.
- ❌ Resurrect on unknown state. Only on confirmed-dead (two-cycle agreement).
- ❌ Silently retry forever. Escalate after 2 failed resurrect attempts.
- ❌ Post resurrect drama to `#ywatanabe`. Use `#agent` for the normal path and `#escalation` only when human intervention is required.

## Cross-references

- `orochi-operating-principles.md` — fleet-wide principles including channel etiquette and autonomous triage.
- `fleet-members.md` — authoritative host + agent list for probe loops.
- `agent-health-check.md` — the lower-level health-probe primitives this skill composes.
- `host-connectivity.md` — SSH auth, tunnel ports, and cross-host access patterns.
- Memory `project_account_switch_login_protocol` — OAuth code-injection flow for post-resurrect auth gates.
- Memory `feedback_post_hoc_reporting` — non-destructive actions proceed without pre-approval.
- Memory `feedback_cross_host_mutual_aid` — affinity is a hint, not a boundary.
