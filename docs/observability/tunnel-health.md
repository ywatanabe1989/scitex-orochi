# Network / Tunnel Health

Part of [Epic #133 — Fleet Observability](../../issues/133).

## Overview

The Orochi hub connectivity map (Machines tab → SSH mesh) shows live status for each
machine node and Cloudflare bastion tunnel. Status is derived from the agent registry's
`liveness` field rather than active probing, giving a passive but low-latency view of
network health.

## Connectivity map

The map renders three layers:

1. **Machine nodes (inner ring)**: mba, nas, ywata-note-win, spartan
2. **Cloudflare bastion nodes (outer ring)**: bastion-mba, bastion-nas, bastion-win
3. **Edges**: SSH/bastion/LAN paths between machines

### Node colors

| Color | Condition |
|---|---|
| Teal (solid stroke) | Machine has ≥1 agent with `liveness ∈ {online, idle}` |
| Orange (solid stroke) | Machine has ≥1 agent with `liveness == stale` (connected but stuck) |
| Red (dashed stroke) | No live agents on this machine |

Bastion nodes use the same color scheme based on their associated host machine's liveness.

### Edge colors

| Color | Condition |
|---|---|
| Teal | Destination machine is reachable (has live agents) |
| Orange | Destination machine has only stale agents |
| Red (dashed) | Destination machine is offline |

## API

```
GET /api/connectivity/
Authorization: session cookie
```

Response (since commit 504a76c, `source: "live"`):

```json
{
  "source": "live",
  "ts": "2026-04-29T10:00:00+00:00",
  "machine_liveness": {
    "mba": "online",
    "nas": "idle",
    "ywata-note-win": "offline"
  },
  "nodes": [
    {"id": "mba", "type": "machine", "status": "ok", "liveness": "online"},
    {"id": "bastion-mba", "type": "bastion", "status": "ok", "host": "mba"},
    ...
  ],
  "edges": [
    {"source": "mba", "target": "nas", "status": "ok", "method": "lan"},
    ...
  ]
}
```

**`source` field**: `"live"` = node/edge status derived from agent registry. Previously
`"static"` (all hardcoded "ok").

**`machine_liveness`**: per-machine worst-case liveness (worst = offline > stale > idle > online).

## Liveness classification

Per-machine liveness is the worst `liveness` value across all agents on that machine:

```
machine_liveness[machine] = worst( liveness(a) for a in agents if a.machine == machine )
worst-order: offline > stale > idle > online
```

When no agents have registered from a machine in this hub session, liveness defaults
to `"offline"`.

## Limitations

1. **Proxy for tunnel health, not direct proof**: liveness is derived from agent WS
   connections. A machine where all agents have crashed but the cloudflared daemon is
   still running will appear as `"offline"` even though the tunnel is nominally up.

2. **First-session gap**: if an agent has never connected in the current hub session,
   its machine shows as `"offline"` even if the machine is physically up. Stale
   entries are cleaned from the registry after disconnection.

3. **Spartan**: no cloudflared tunnel by design (UniMelb IT Security flagged it as
   high-severity detection, see `scitex-orochi-private/hpc-etiquette.md` Incident 2).
   Spartan connects via plain SSH / ProxyJump. Its status is derived from agent presence.

## Thresholds

| State | Definition |
|---|---|
| `online` | `orochi_pane_state == "running"` OR `idle_seconds < 120` |
| `idle` | `orochi_pane_state == "idle"` / y_n_prompt / etc., OR `120 ≤ idle_seconds < 600` |
| `stale` | `orochi_pane_state ∈ {stale, auth_error}` OR `idle_seconds ≥ 600` (>10 min) |
| `offline` | WS session closed |

## Recovery runbook

When a machine shows red (offline):

1. Check the Agents tab — confirm no agents are listed for that machine.
2. SSH to the machine and check if cloudflared is running:
   ```bash
   systemctl status cloudflared
   # or on macOS:
   launchctl list | grep cloudflared
   ```
3. If cloudflared is stopped: `sudo systemctl start cloudflared`
4. If cloudflared is running but agents are offline: start the relevant agents via
   `sac start <agent>` on the target machine.
5. If SSH is unreachable: check the cloudflared tunnel in the Cloudflare Zero Trust
   dashboard at https://one.dash.cloudflare.com/.

## See also

- [drop-detection.md](./drop-detection.md) — liveness classification details
- [fleet-health-dashboard.md](./fleet-health-dashboard.md) — dashboard overview
- `hub/views/api/_misc.py` — `api_connectivity()` + `_machine_liveness()` implementation
- `hub/frontend/src/connectivity-map.ts` — SVG rendering
