---
name: orochi-hub-stability
description: Hub failure modes, WebSocket ping/pong architecture, diagnostic flowchart, and recovery procedures. Post-mortem from 2026-04-14 incident.
---

# Hub Stability

## Two-Layer Ping/Pong Architecture

WebSocket keep-alive operates at two independent layers:

| Layer | Who sends | Who responds | Protocol |
|-------|-----------|--------------|----------|
| **Protocol-level** | Client (MCP sidecar) | Server (Daphne) | RFC 6455 PING frame |
| **App-level** | Server (Django consumer) | Client (agent) | JSON `{"type": "ping"}` / `{"type": "pong"}` |

**Critical**: Daphne does **not** respond to protocol-level PING frames from clients. Protocol-level pings must flow server → client. Agent MCP sidecars send app-level JSON pings; the Django consumer responds with JSON pong. If the consumer is stuck, app-level pings go unanswered even though the TCP/TLS connection stays open — agents appear connected but receive nothing.

Daphne settings (production):

```
--ping-interval 20   # server sends protocol-level ping every 20s
--ping-timeout 30    # disconnects if no pong within 30s
-t 120               # HTTP timeout 120s
```

## Failure Mode Diagnosis by HTTP Status

| Status | Meaning | Layer broken |
|--------|---------|--------------|
| **530** | Cloudflare can't reach origin | `cloudflared` tunnel broken on MBA |
| **502** | Origin connected but upstream stuck | Daphne hung (deadlock / OOM) |
| **500** | Origin reached, application crashed | Daphne / Django unhandled exception |
| **101** (no traffic) | WS open but no messages | Consumer stuck, app-level ping unanswered |

Quick check:

```bash
curl -sI https://scitex-orochi.com/api/health/
# 200 → hub alive; 530 → cloudflared; 502/500 → Daphne
```

## Recovery Procedures

### 530 — cloudflared Broken (MBA)

```bash
# On MBA — get sudo via decrypt.sh
~/.dotfiles/scripts/decrypt.sh -t mba.ssl    # unlocks sudo for ~5 min

# Kill stale tunnel and restart via launchctl
sudo killall cloudflared 2>/dev/null || true
sudo launchctl kickstart -k system/com.cloudflare.cloudflared
```

Verify recovery:

```bash
sleep 5 && curl -sI https://scitex-orochi.com/api/health/ | head -1
# expect: HTTP/2 200
```

### 502 — Daphne Stuck (NAS Docker)

```bash
ssh nas 'docker restart orochi-server-stable'
```

Wait 10s, then verify agents reconnect via `/api/agents`.

### 500 — Django Crash

```bash
ssh nas 'docker logs orochi-server-stable --tail 100'
# identify the traceback, fix in code, then hot-deploy (see hub-deploy-hotfix.md)
ssh nas 'docker restart orochi-server-stable'
```

## MCP Sidecar Hub-Unreachable Alarm

Each agent's MCP sidecar monitors send success. If any `reply` call fails for **60 consecutive seconds**, the sidecar:

1. Logs `HUB_UNREACHABLE` to local agent log.
2. Posts a notification to `#escalation` via the backup HTTP fallback (if available).
3. Begins exponential-backoff reconnect attempts (1s → 2s → 4s … cap 60s).

Agents do **not** exit on hub unreachability — they wait and reconnect automatically.

## LaunchAgent Respawn Storms

**Problem**: When the hub goes down, all agents on MBA disconnect simultaneously. macOS `launchd` respawns them all at once. All reconnect simultaneously → Daphne is flooded → all time out → all respawn again → loop.

**Solution**: `ThrottleInterval = 120` in every agent's `.plist`. This prevents launchd from respawning the agent more than once per 120 seconds, breaking the storm cascade.

```xml
<!-- In ~/Library/LaunchAgents/com.scitex.orochi.<agent>.plist -->
<key>ThrottleInterval</key>
<integer>120</integer>
```

**Cascade anatomy**:

```
Hub down → agents disconnect
  → launchd respawns all at once (T+0s)
  → all reconnect simultaneously → Daphne overloaded
  → connection timeouts for all → all die again
  → launchd respawns all at once (T+5s) [ThrottleInterval missing]
  → loop indefinitely
```

With `ThrottleInterval=120`, each respawn wave is at most 1 agent per plist, spaced 120s apart — Daphne handles reconnects gracefully.

## cloudflared-watchdog.sh

Location: `~/proj/scitex-orochi/deployment/fleet/cloudflared-watchdog.sh`

Probes the hub every 30s. On 530 response:

1. Kills and restarts `cloudflared` via launchctl.
2. Waits up to 30s for recovery.
3. Posts to `#escalation` if recovery fails after 3 attempts.

Run via cron on MBA (as root or with sudo rights via decrypt.sh):

```bash
# Check if watchdog cron is active
sudo crontab -l | grep cloudflared-watchdog
# Install:
echo "*/1 * * * * /Users/ywatanabe/proj/scitex-orochi/deployment/fleet/cloudflared-watchdog.sh >> /tmp/cloudflared-watchdog.log 2>&1" | sudo crontab -
```

## agent-respawn.sh

Location: `~/proj/scitex-orochi/deployment/fleet/agent-respawn.sh`

Used to restart all agents on a host in a controlled order with a **10-second throttle** between each start, preventing reconnect storms.

```bash
~/proj/scitex-orochi/deployment/fleet/agent-respawn.sh
# Starts agents one by one with 10s gaps
# Safe to run after any hub outage or host reboot
```

Never restart all agents simultaneously by hand — always go through `agent-respawn.sh` or space starts by at least 10s.

## 2026-04-14 Incident Post-Mortem

**Timeline**:
- Hub became unreachable; HTTP status 530 → cloudflared tunnel dropped.
- Agents on MBA all died simultaneously.
- launchd respawned all at once (ThrottleInterval not set).
- Hub recovered but was immediately overwhelmed by reconnect storm → 502.
- Storm looped for ~15 minutes.

**Fixes applied**:
- Added `ThrottleInterval=120` to all agent plists.
- Deployed `cloudflared-watchdog.sh` as a cron job.
- Added `agent-respawn.sh` for controlled mass-restart.
- Documented two-layer ping/pong distinction (root of why "agents show connected but receive nothing" is a consumer-stuck symptom, not a network issue).
