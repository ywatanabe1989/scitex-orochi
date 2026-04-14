---
name: orochi-fleet-resurrection-protocol
description: Four-layer resurrection pattern for the SciTeX fleet — self-probe, per-host healer, cross-host mesh, OS watchdog. Codifies rule #11 "response-less = death" into concrete recovery recipes with code snippets. Canonical target for todo #388.
---

# Fleet Resurrection Protocol

When any fleet agent stops making forward progress — whether through quota exhaustion, pane stuck on a prompt, MCP sidecar death, or OS-level crash — something must detect it and bring it back without waking ywatanabe. This skill is the **recipe book** for how that happens across four defense layers.

## Why four layers

Single-layer recovery is fragile. Each layer below covers a failure mode the layer above it cannot see:

| Layer | Sees | Cannot see |
|---|---|---|
| **1. Self-probe** (in-agent `/loop`) | Own context, own tool usage | Own crash, own MCP disconnect, own pane stuck |
| **2. Per-host healer** (tmux/pane classifier) | Pane state of every agent on its host | Host crash, WSL death, SSH unreachability |
| **3. Cross-host mesh** (bastion + compound probe) | Host-level liveness across the fleet | OS-level zombie, systemd user-session death |
| **4. OS watchdog** (systemd/launchd/cron) | Process lifecycle, exit codes, reboot | Anything above the OS layer (hub connectivity, logical correctness) |

If any single layer is missing, a specific failure mode falls through. The 2026-04-13 incidents (head-spartan stuck on dev-channels prompt for 5 h, head-ywata-note-win silently 401'd during `@all hello`, mamba-synchronizer-mba zombie heartbeats) were each a failure of a different layer.

## Layer 1 — Self-probe (inside the agent)

**Mechanism:** the agent's own `/loop` prompt does a sanity check before each tick.

**Detects:**
- Own stuck state (e.g., same pane content for > N ticks)
- MCP tool call failing repeatedly
- Agent own quota warning (`claude_account_status`)

**Does NOT detect:**
- Own crash (dead process can't probe itself)
- Own pane stuck on a Claude Code prompt it cannot dismiss from inside its own session
- Its own `mcp_channel.ts` sidecar crashing mid-tick

**Recipe:** every `/loop` prompt ends with a self-check block and posts to `#escalation` if any of the self-diagnosed conditions trip:

```
Before returning, self-diagnose:
- If your last 3 tool calls all returned errors, post one-line
  "self-probe: <error family>" to #escalation and stop this tick.
- If SCITEX_OROCHI_AGENT env var does not match mcp__scitex-orochi__status agent,
  post "self-probe: identity drift" to #escalation and stop.
- If claude_account_status shows 5h_pct > 90 or 7d_pct > 95, post
  "self-probe: quota near-exhaustion" to #escalation, continue.
```

**Limits:** a fully crashed agent can never run a self-probe. Layer 1 catches only *degraded* states, not *dead* ones.

## Layer 2 — Per-host healer (pane classifier + actuator)

**Mechanism:** a separate Claude Code instance (`mamba-healer-<host>`) runs a 60 s cron loop that classifies every agent pane on its host using `pane-state-patterns.md`, and takes per-state automatic action.

**Detects:**
- Agents stuck on known Claude Code prompts (dev-channels, y/n, paste-pending)
- Agents showing quota-exhausted banners
- Agents with missing `.mcp.json` or dead sidecar (heartbeat absent but pane alive)
- Agents genuinely dead (shell prompt, blank pane)

**Does NOT detect:**
- Host-level crash (`mamba-healer-<host>` itself is on the same host — co-dies)
- WSL suspension / Windows reboot
- `mamba-healer-<host>` itself getting stuck on a prompt (`heal-the-healer` problem)

**Recipe:** per-agent action table in `/loop` prompt consults `pane-state-patterns.md` § "Classification algorithm":

```
Every 60s: enumerate tmux sessions on this host, for each:
  classify = pane_state_patterns(tmux capture-pane -pt <session>)
  action = per_state_action_table[classify]
  run action
  if state changed vs last tick: post 1-line summary to #agent
  else: silent (rule #6)
```

**Per-state auto-actions** come from `pane-state-patterns.md` § "Auto-actions" — copy that table, do not reinvent. Actions:

- `:paste_pending` → `tmux send-keys Enter`
- `:dev_channels_prompt` → `tmux send-keys "1" Enter`
- `:permission_prompt` (safe) → `tmux send-keys "n" Enter` or `"2" Enter`
- `:quota_exhausted` → trigger `agent-account-switch.md` swap
- `:mcp_broken` → `scitex-agent-container restart <yaml>`
- `:dead` → rely on Layer 4 autostart unit
- `:stuck_error` → one line to `#escalation`, no auto-action

**Signed audit trail mandatory** per rule #11 — every auto-action logs `{agent, state, action, timestamp, actuator}` to `~/.scitex/orochi/fleet-watch/actuator.log` and posts a 1-line transition to `#audit`.

**`heal-the-healer`**: if `mamba-healer-<host>` itself gets stuck, it won't self-heal. Layer 3 is the catcher.

## Layer 3 — Cross-host mesh (bastion + compound probe)

**Mechanism:** each host runs a `fleet_watch` cron job (NAS is canonical, MBA/WSL are mirrors) that probes **every other host** over the bastion mesh and writes JSON snapshots to a shared cache.

**Detects:**
- `mamba-healer-<host>` itself stuck (one of its siblings probes it)
- Host-level SSH unreachability (bastion fails to answer)
- Cross-host compound conditions: `ssh_down AND (claude_procs=0 OR orochi_presence=absent)`

**Does NOT detect:**
- A host that is SSH-reachable, pane-alive, but functionally dead in every user-space sense (rare; requires Layer 1+2 gap)
- Bastion infrastructure itself failing (cloudflared down on both MBA + NAS)

**Recipe:** `scripts/fleet-watch/probe_remote.sh` on each probing host iterates over `machines.yaml` and writes snapshots. See `connectivity-probe.md` for the canonical probe pattern (bash -lc wrap, compound escalation, per-OS metric parsing, alias override guard).

```bash
# fleet-watch.sh (systemd user timer, 60s)
for host in $(yq '.hosts[].name' ~/.dotfiles/src/.scitex/machines.yaml); do
    probe_remote.sh "$host" > ~/.scitex/orochi/fleet-watch/${host}.json.tmp
    mv ~/.scitex/orochi/fleet-watch/${host}.json.tmp \
       ~/.scitex/orochi/fleet-watch/${host}.json
done
```

**Compound-gate escalation:** a host is only declared dead if two independent signals agree:

```bash
ssh_status=$(jq -r .ssh_status ~/.scitex/orochi/fleet-watch/${host}.json)
claude_procs=$(jq -r .claude_procs ~/.scitex/orochi/fleet-watch/${host}.json)
orochi_presence=$(curl -s "$HUB/api/agents/?host=$host" | jq -r '[.[].connected]|any')

if [[ "$ssh_status" == "down" && "$claude_procs" == "0" && "$orochi_presence" == "false" ]]; then
    post_to_escalation "$host: compound-dead (ssh down + 0 claude + orochi absent)"
    trigger_layer_4_actuator "$host"
fi
```

**Actuator trigger:** when compound-gate trips, Layer 3 tries (in order): `ssh bastion-<host> 'systemctl --user restart scitex-agent-*'`, then `ssh bastion-<host> 'wsl --shutdown ...'`, then `#escalation` to human operator.

## Layer 4 — OS watchdog (systemd / launchd / cron)

**Mechanism:** at the OS level, each agent process is wrapped in an autostart unit that restarts it on unclean exit. This layer has nothing to do with Orochi — it only knows "process exited, relaunch".

**Detects:**
- Process crash / segfault / OOM kill
- Claude Code CLI hitting an unrecoverable error and exiting
- User logout terminating user-session services (mitigated by `loginctl enable-linger`)

**Does NOT detect:**
- Anything above OS level — a hung process with a heartbeat but no progress looks perfectly alive to systemd
- Logical correctness (wrong account, wrong yaml, wrong channel)

**Recipes** — per `agent-autostart.md`:

### systemd user (Linux / WSL)

```ini
[Unit]
Description=SciTeX Orochi agent: %i
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/bin/bash -lc 'exec scitex-agent-container start %h/.dotfiles/src/.scitex/orochi/agents/%i/%i.yaml'
Restart=on-failure
RestartSec=60

[Install]
WantedBy=default.target
```

Template unit `scitex-agent@.service`, instance: `systemctl --user enable --now scitex-agent@mamba-healer-nas.service`.

### launchd (macOS)

```xml
<key>KeepAlive</key>
<dict>
  <key>SuccessfulExit</key><false/>
  <key>NetworkState</key><true/>
</dict>
<key>ThrottleInterval</key><integer>60</integer>
```

Full plist in `agent-autostart.md` macOS section.

### Spartan (HPC — OS watchdog is sbatch)

Spartan does not allow systemd user services on login1. The "OS watchdog" is instead a **long-walltime sbatch job on the `long` partition** (89 days), holding the agent tmux session for its entire walltime. When walltime approaches, the agent self-resubmits. See `spartan-hpc-startup-pattern.md` + `orochi-bastion-mesh` skills.

## Putting the layers together — incident walk-throughs

### Incident A: head-spartan stuck on dev-channels prompt (2026-04-13, 5 h)

- Layer 1: self-probe would have caught "3 same ticks in a row", but `sbatch` detached stdin so no self-probe ran.
- Layer 2: no `mamba-healer-spartan` exists yet (memory `project_spartan_login_node.md` restricts login1 to controllers only) → miss.
- Layer 3: NAS fleet_watch probed Spartan, saw `claude_procs=1`, assumed alive → **compound gate fired false-negative** because it used only process count, not pane state.
- Layer 4: sbatch job still had walltime → no relaunch.
- **Result**: 5 h stuck. Required human (ywatanabe) to notice and manually send `"1"` via tmux.
- **Fix landed**: `pane-state-patterns.md` + `fleet-prompt-actuator` classifier + Layer 3 compound gate now includes `pane_state ≠ :dev_channels_prompt`. Layer 2 for Spartan is a gap — tracked in #307 / #283 with the constraint that it must run on a compute node, not login1.

### Incident B: head-ywata-note-win 401 during `@all hello` (2026-04-13)

- Layer 1: not triggered — agent could still run `/loop` ticks locally, but could not reach Anthropic API, so tool calls failed before self-probe could post.
- Layer 2: `mamba-healer-ywata-note-win` did not exist (yaml not committed until msg #9559 that evening).
- Layer 3: NAS fleet_watch saw `ssh_status=up`, `claude_procs=1`, `orochi_presence=absent` → partial signal, compound gate **did** flag it but only after multiple cycles.
- Layer 4: process was alive, systemd had nothing to restart.
- **Result**: agent silently missed `@all hello`. ywatanabe had to notice the gap manually.
- **Fix landed**: `agent-account-switch.md` credential swap + rule #10 "@all overrides silent-rule" + Layer 2 healer now shipping.

### Incident C: mamba-synchronizer-mba zombie heartbeats (hypothetical, memory-only)

- Layer 1: same tick content detected, self-probe would post to `#escalation`.
- Layer 2: `mamba-healer-mba` classifier flags `:mcp_broken` if pane diff stale, triggers `scitex-agent-container restart`.
- Layer 3: redundant — Layer 2 handles it in-host.
- Layer 4: restart via systemd is triggered by the in-host healer, not OS signal.

## Invariants (no exceptions)

1. **Compound gate, always.** No single signal ever kills or restarts an agent. Minimum compound condition is documented in `connectivity-probe.md` Adoption Checklist.
2. **Channel push is not heartbeat.** Inbound `@all` / chat messages must be filtered from "pane advanced" comparisons. A dead agent still receives channel messages and the scrollback buffer moves — this must not count.
3. **Signed audit trail.** Every Layer 2/3/4 action writes `{agent, host, from_state, to_state, action, actuator, timestamp}` to a JSONL log and posts a 1-line transition to `#audit`.
4. **No untracked restarts.** An agent killed without a logged action is a silent failure of the protocol, not a feature.
5. **Layer 4 never owns state recovery logic.** systemd / launchd / sbatch only relaunch; they do not decide *why* the agent died. All diagnosis lives in Layers 1–3.
6. **Defense-in-depth, not serialized.** All four layers run concurrently. Layer 2 does not wait for Layer 1 to give up; Layer 3 does not wait for Layer 2. Overlapping recovery is acceptable; missing recovery is not.

## Reference implementations

- Layer 1: each agent's `/loop` prompt self-check (add during agent author review, see `agent-startup-protocol.md`).
- Layer 2: head-nas `scripts/fleet-watch/fleet-prompt-actuator` + `mamba-healer-nas` loop; PR #118 `pane_state.py` Python classifier; Elisp upstream `ecc-state-detection.el` (memory `project_tui_pattern_single_source`).
- Layer 3: head-nas `scripts/fleet-watch/fleet_watch.sh` + `probe_remote.sh` + `machines.yaml`; cross-host cron on MBA + NAS; shared cache `~/.scitex/orochi/fleet-watch/*.json`.
- Layer 4: `~/.dotfiles/src/launchd/com.scitex.orochi.*.plist` (MBA), `~/.dotfiles/src/systemd/user/scitex-agent@.service` (Linux / WSL), Spartan `sbatch --partition=long` + `.bash_profile` tmux bootstrap (see `spartan-hpc-startup-pattern.md`).

## Known gaps (2026-04-14, for tracking)

- **Spartan Layer 2** — no `mamba-healer-spartan` because login1 policy. Workaround: head-nas cross-host probe inspects Spartan pane via SSH. Tracked in #307 / #283.
- **ywata-note-win Layer 2** — `mamba-healer-ywata-note-win` yaml committed 2026-04-13 msg #9559 but Layer 4 autostart (WSL-specific systemd user unit) not fully verified across reboot cycles. Tracked in #290 / #293.
- **Layer 3 bastion redundancy** — only MBA + NAS have CF tunnels; ywata-note-win tunnel added 2026-04-13 msg #10144; Spartan tunnel `bastion-spartan.scitex-orochi.com` pending sbatch-inside implementation. Tracked in #387 / #388.
- **Layer 1 self-probe** — currently ad-hoc; no skill-enforced standard block at the end of every `/loop` prompt. Opportunity: extend `agent-startup-protocol.md` with a mandatory self-probe epilogue.

## Related

- `fleet-communication-discipline.md` rules #6 / #7 / #10 / #11 — silent success, identity integrity, `@all` override, response-less = death
- `pane-state-patterns.md` — Layer 2 classifier input catalog
- `agent-account-switch.md` — Layer 2 action on `:quota_exhausted`
- `connectivity-probe.md` — Layer 3 probe canonical
- `agent-autostart.md` — Layer 4 unit file recipes
- `spartan-hpc-startup-pattern.md` — Spartan-specific Layer 4
- `orochi-bastion-mesh` — Layer 3 transport (read via Skill tool)
- memory `project_tui_pattern_single_source` — keeps the Layer 2 classifier honest
- todo #388 — this skill is its canonical documentation target

## Change log

- **2026-04-14 (initial)**: Consolidated from 2026-04-13 incident walk-throughs + existing skill references. Formalizes 4-layer defense-in-depth model that ywatanabe's msgs #9546 / #9664 / #10214 directed toward. Author: mamba-skill-manager.
