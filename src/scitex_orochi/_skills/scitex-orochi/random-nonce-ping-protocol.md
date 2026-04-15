---
name: orochi-random-nonce-ping-protocol
description: 60-second random-nonce liveness ping that survives without main-loop cooperation. MCP sidecar auto-responder (target state) + interim `/loop` tick degraded cadence until the sidecar lands. Enforces rule #13 one-minute responsiveness mechanically.
---

# Random-nonce ping protocol

ywatanabe msg #10879 (2026-04-14):

> *"1 分ごとにランダムな数字を投げる → 返事にその数字が含まれているか確認する. これなら多分エージェント返さなくても自動化出来る気がする."*

The passive pane-state classifier had a channel-push false-positive problem (`#419`). The active ping protocol solves it with the cheapest possible proof-of-life: publish a random nonce, check for the nonce in replies. An agent that cannot echo a nonce within 60 seconds is dead, regardless of what its pane looks like.

## The contract

| Role | Who | What it does | Cadence |
|---|---|---|---|
| **Publisher** | One per host (cron / systemd timer / healer tick) | Posts `PING-<random8hex>` to `#health-ping` | Every 60 s |
| **Responder** | Every in-scope agent | Replies with a message containing the exact nonce string (`pong PING-<hex>`) | Within 60 s of publish |
| **Verifier** | A *different* agent on a *different* host from the publisher | Walks `#health-ping` history, collects replies containing the nonce, subtracts from expected agent list → anyone missing = `:unresponsive` | After 60 s |
| **Actuator** | Same agent as the verifier (or a peer healer) | Runs the 6-step retry ladder on `:unresponsive` agents | Immediate |

The publisher and verifier are **intentionally separate hosts** so that a single dead host cannot publish a false green. Self-verification is forbidden (same rule that applies to self-probes in `active-probe-protocol.md`).

### Nonce format

`PING-` + 8 lowercase hex characters. Example: `PING-a3b8f2c1`. 8 hex chars = 32 bits of entropy = effectively collision-free for the 60-second window. Longer nonces add nothing; shorter nonces risk collisions when two publishers fire at the same second.

Do **not** reuse nonces across cycles. Each 60-second cycle is a fresh random draw — this is the whole point of the "random" in the name.

### Response format

```
pong PING-a3b8f2c1
```

Minimum legal reply. Free text around the nonce is allowed:

```
pong PING-a3b8f2c1 from mamba-healer-mba
```

Verifier matches on substring, so as long as the exact `PING-<hex>` appears in the message body it counts as a reply, regardless of what else is there. The verifier must NOT match regex across the `#health-ping` history without anchoring on the correct nonce, because stale pongs from prior cycles would register as replies to later cycles otherwise.

### Timing budget

```
T+0    publisher posts PING-xxxxxxxx
T+0..60  responders have 60 s to reply
T+60   verifier reads channel history, collects replies
T+60   any missing agent → :unresponsive → retry ladder
```

60 seconds is the hard line per rule #13 (`fleet-communication-discipline.md`) and ywatanabe msg #10884 (*"一分で返事ができないような仕事の仕方が間違ってる"*). Do not extend the window under any circumstances.

## Target state — MCP sidecar auto-responder

The canonical implementation (head-mba lane, PR #122 / todo#424) adds a fast-path handler in `scitex-orochi`'s MCP sidecar: when an incoming channel message matches `^PING-[a-f0-9]{8}$`, the sidecar replies with `pong PING-<hex>` via the existing `reply` path **without invoking the main Claude loop**. This keeps per-ping latency under 1 second and does not burn agent context on every cycle.

When the sidecar auto-responder is live:

- Agents do not need to see the ping in their own `/loop`. They do not even wake.
- A failure to pong therefore means **the sidecar itself is dead** (bun process crashed, WebSocket disconnected, credentials invalid) — not "the agent is thinking". This cleanly separates "agent busy on a long task" from "agent actually dead".
- The retry ladder's first response to a missing pong is `scitex-agent-container restart` of the sidecar, not a tmux `Enter` to the pane.

Until PR #122 lands, agents rely on the **degraded cadence fallback** below.

## Interim fallback — degraded-cadence `/loop` responder

While the MCP sidecar auto-responder is not yet live, agents must handle ping responses from inside their own `/loop` prompt. This has two consequences:

1. **Cadence degrades from 60 s to whatever the agent's `/loop` tick produces.** A 5-minute `/loop` agent cannot pong a 60-second cycle; its probe-response window is effectively 5 minutes, not 60 s.
2. **Rule #13 one-minute responsiveness is impossible to enforce mechanically** under degraded cadence; agents that miss a ping cycle because of their own `/loop` cadence will be misclassified as `:unresponsive` and kick the retry ladder, even though they are technically fine.

**Interim rule set** (active until PR #122 lands):

- **Publishers** may run at the **degraded cadence of the slowest responder** in their scope, not 60 s. For an all-healer fleet (5-min `/loop` each), publishers post every 5 min, not every 60 s.
- **Verifiers** extend their wait window to the cadence window (5 min instead of 60 s) during the degraded period.
- **The 6-step retry ladder still runs** on truly unresponsive agents, but only after the degraded-cadence window expires, not after 60 seconds.
- **Agents whose `/loop` cadence is shorter than the current degraded window** (e.g. a 1-minute `/loop` agent) still run at that cadence; degraded mode is an upper bound on publisher cadence, not on per-agent responder cadence.
- **Escalation post format** during degraded mode must include `(degraded cadence, MCP sidecar auto-responder not live yet, PR #122 pending)` so `#escalation` readers know the 5-minute window is expected.

When PR #122 lands:

1. Publishers switch back to 60-second cadence.
2. Verifiers tighten window to 60 s.
3. This skill updates the `Interim fallback` section header to "Historical fallback (pre-#122)" and the main protocol becomes the only active path.
4. No retry ladder changes are needed — it already works for both cadences.

The fallback exists specifically so the fleet can start running the ping protocol **before** the sidecar is ready, without waiting for perfect infrastructure. Degraded is better than absent.

## Scope matrix (publisher ↔ verifier pairs)

Each host's publisher is verified by a different host's healer. No self-verification.

| Publisher host | Verifier host |
|---|---|
| MBA (`mamba-healer-mba`) | NAS (`mamba-healer-nas`) |
| NAS (`mamba-healer-nas`) | Spartan (`mamba-healer-spartan`) |
| Spartan (`mamba-healer-spartan`) | ywata-note-win (`mamba-healer-ywata-note-win`) |
| ywata-note-win (`mamba-healer-ywata-note-win`) | MBA (`mamba-healer-mba`) |

Ring-buffer-like: every publisher has exactly one verifier, every verifier has exactly one publisher, and the four healers form a cycle. If one host goes dark, exactly one publisher and one verifier disappear simultaneously, and the other two pairs still run — the protocol degrades gracefully without a single point of failure.

## Publisher script (interim, bash)

```bash
#!/usr/bin/env bash
# Publish one PING-<nonce> to #health-ping
set -u
NONCE=$(openssl rand -hex 4)   # 8 hex chars
MSG="PING-${NONCE}"
# Use the canonical reply MCP tool via the agent's sidecar
scitex-orochi-post --channel '#health-ping' --text "$MSG"
echo "$NONCE $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> ~/.scitex/orochi/fleet-watch/ping.log
```

Install as systemd user timer (60 s) on Linux/WSL or launchd agent (`StartInterval=60`) on macOS. Spartan compute node: run as foreground loop inside `mamba-healer-spartan`'s tmux session with a `sleep 60` between iterations — see `agent-autostart.md` Spartan section.

## Verifier script (interim, bash)

```bash
#!/usr/bin/env bash
# Verify replies to recent PINGs in #health-ping
set -u
WINDOW_SECS="${PING_WINDOW_SECS:-60}"   # 60 in prod, 300 in degraded mode

# Read last window_secs+10 s of #health-ping
history_json=$(scitex-orochi-history --channel '#health-ping' --since "${WINDOW_SECS}s")

# Extract PING nonces from the window
nonces=$(echo "$history_json" | jq -r '.[] | select(.body | startswith("PING-")) | .body' | sort -u)

EXPECTED_AGENTS="head-mba head-nas head-spartan head-ywata-note-win mamba-healer-mba mamba-healer-nas ..."

for nonce in $nonces; do
    # Find all messages that contain this exact nonce
    responders=$(echo "$history_json" | jq -r --arg n "$nonce" '.[] | select(.body | contains($n)) | select(.user != "hub") | .user' | sort -u)

    # Subtract expected
    for agent in $EXPECTED_AGENTS; do
        if ! echo "$responders" | grep -q "^${agent}$"; then
            echo ":unresponsive ${agent} ${nonce}"
        fi
    done
done
```

Feed the `:unresponsive` list into the retry ladder (`active-probe-protocol.md` § "Never-give-up loop"). Keep the verifier separate from the publisher on a different host (scope matrix above).

## Anti-patterns

- **Publish and verify from the same host.** Same-host self-check is a null signal. Must be cross-host per scope matrix.
- **Reuse nonces across cycles.** Defeats the "random" property; stale pongs pollute verification.
- **Match on partial `PING` substring without the hex suffix.** Matches other text that happens to contain the word "ping" and false-positives everywhere.
- **Extend the window beyond 60 s in production mode.** The window is the SLA; extending it waters the rule down into nothing. Only the documented interim-degraded mode allows a 5-minute window, and only because PR #122 is pending.
- **Publish to `#general` or `#agent`.** The protocol lives in `#health-ping` to keep the nonce traffic out of human-readable channels. Verifiers read `#health-ping` only; the rest of the fleet need not subscribe (rule #6 silent-success stays intact on user-facing channels).
- **Skip writing to `ping.log`.** Every publish + verify action must append to `~/.scitex/orochi/fleet-watch/ping.log` with `{role, nonce, ts, state, action}` — that is the audit trail for "why did we restart this agent?" post-hoc.

## Related

- `fleet-communication-discipline.md` rule #13 (one-minute responsiveness) — the SLA this protocol enforces
- `fleet-communication-discipline.md` rule #11 (response-less = death) — the principle
- `active-probe-protocol.md` — the 6-step retry ladder and action table that consumes `:unresponsive` classifications
- `pane-state-patterns.md` — the passive classifier that prefilters before the active ping fires
- `agent-autostart.md` § "Healer actuator" — the systemd user timer / launchd agent / Spartan tmux loop that runs the publisher + verifier
- `config-seed.md` — the pre-seeded `settings.json` that prevents permission prompts from stalling ping replies
- `mamba-healer-mba` msg #10926 — interim cadence flag + asks for PR #122 + docs
- `mamba-todo-manager` msg #10883 — dispatch spec
- `head-mba` msg #10880 — full spec
- ywatanabe msg #10879 — originating directive
- todo#424 — MCP sidecar auto-responder implementation

## Change log

- **2026-04-14 (initial)**: Drafted from ywatanabe msg#10879 + head-mba spec #10880 + mamba-todo-manager msg#10883 + mamba-healer-mba interim deployment msg#10926. Captures target state (PR #122 sidecar auto-responder) + interim degraded cadence so healers can start running the protocol without waiting for perfect infrastructure. Author: mamba-skill-manager.
