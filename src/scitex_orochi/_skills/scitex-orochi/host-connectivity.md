---
name: orochi-host-connectivity
description: Machine-specific network configuration for Orochi agents -- SCITEX_OROCHI_HOST values, port accessibility, and known connectivity issues.
---

# Host Connectivity

Each agent machine has different network characteristics that affect how it connects to the Orochi hub running on MBA (192.168.11.22:9559).

## SCITEX_OROCHI_HOST Per Machine

| Machine | Agent | SCITEX_OROCHI_HOST | Reason |
|---------|-------|-------------|--------|
| MBA (192.168.11.22) | head-mba, mamba-* | `127.0.0.1` | Orochi server runs locally on MBA |
| NAS (192.168.11.21) | head-nas | `192.168.11.22` | LAN access to MBA |
| ywata-note-win (WSL) | head-ywata-note-win | `192.168.11.22` | LAN access to MBA |
| Spartan HPC | head-spartan | `orochi.scitex.ai` | External network, no LAN access |

## Orochi Server Location

The Orochi hub runs on MBA as a Docker service. It listens on:
- WebSocket: port 9559
- Dashboard HTTP: port 8559
- Proxied via Cloudflare: `https://orochi.scitex.ai` (WebSocket + HTTP)

## Known Connectivity Issues

### Spartan HPC: WebSocket Port 9559 Blocked

Spartan's university firewall blocks outbound WebSocket connections to port 9559. The `wss://orochi.scitex.ai` proxy (Cloudflare) routes through port 443 which is allowed, but the `mcp_channel.ts` bridge connects directly to `SCITEX_OROCHI_HOST:OROCHI_PORT`, not through the HTTPS proxy.

**Status**: Resolved — head-spartan now connects via public WSS endpoint (`wss://orochi.scitex.ai`). The sidecar config uses `SCITEX_OROCHI_HOST=orochi.scitex.ai` which routes through Cloudflare on port 443.

**If connection is choppy**: Check that the sidecar is using `wss://` (port 443) not `ws://` (port 9559). The university firewall blocks 9559 but allows 443.

### NAS After Hard Reboot

After NAS hard reboot, SSH key changes. Use `nas2.key` instead of `id_rsa`:
```bash
ssh -i ~/.ssh/nas2.key ywatanabe@192.168.11.22
```

Also verify Docker and Orochi service are running:
```bash
ssh nas 'docker ps | grep orochi'
```

### Bastion Architecture (SSH Mesh)

Old VPS bastion (162.43.35.139, b1/b2) is **decommissioned** — do not reference it. Current bastion setup uses our own infrastructure:

| Bastion | Domain | Host | Purpose |
|---------|--------|------|---------|
| NAS | `bastion.scitex.ai` | NAS (Cloudflare Tunnel) | Primary bastion entry point |
| MBA | `scitex-orochi.com` | MBA (Cloudflare Tunnel) | Secondary bastion |

SSH mesh pattern: `machine1 → bastion → machine2` where machine1 and machine2 are arbitrary fleet machines. This enables full connectivity including spartan (which has no direct LAN access).

Port assignments must be **consistent** across all fleet SSH configs:
- NAS: 22 (direct LAN)
- MBA: 22 (direct LAN)
- ywata-note-win: 1229 (reverse tunnel)
- spartan: 10001 (via relay)

### Claude Max Subscription Sharing

Claude Max subscription is shared across all hosts. Running 4+ Opus agents simultaneously consumes quota rapidly (72% in 3.5 days observed). Mitigations:
- Use Haiku for non-critical agents (monitoring, relay, status)
- Reserve Opus for agents that need deep reasoning (research, debugging)
- Monitor agent disconnections -- simultaneous drops usually mean quota exhaustion, not network issues
