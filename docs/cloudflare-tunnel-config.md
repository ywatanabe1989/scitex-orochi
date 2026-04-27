# Cloudflare Tunnel Configuration for Orochi Stable/Dev Split

## Required Tunnel Routes

Configure these in the Cloudflare Zero Trust dashboard or `config.yml` on NAS.

### Stable Instance (production)

| Public Hostname         | Service              | Description        |
|------------------------|----------------------|--------------------|
| orochi.scitex.ai       | http://localhost:8559 | Stable dashboard   |
| ws.orochi.scitex.ai    | http://localhost:9559 | Stable WebSocket   |

### Dev Instance (development)

| Public Hostname            | Service              | Description     |
|---------------------------|----------------------|-----------------|
| orochi-dev.scitex.ai      | http://localhost:8560 | Dev dashboard   |
| ws-dev.orochi.scitex.ai   | http://localhost:9560 | Dev WebSocket   |

## Example cloudflared config.yml snippet

```yaml
# Add these ingress rules to the existing tunnel config on NAS
# Location: typically /etc/cloudflared/config.yml or ~/.cloudflared/config.yml

ingress:
  # Stable Orochi
  - orochi_hostname: orochi.scitex.ai
    service: http://localhost:8559
  - orochi_hostname: ws.orochi.scitex.ai
    service: http://localhost:9559

  # Dev Orochi
  - orochi_hostname: orochi-dev.scitex.ai
    service: http://localhost:8560
  - orochi_hostname: ws-dev.orochi.scitex.ai
    service: http://localhost:9560

  # ... existing rules ...
  - service: http_status:404
```

## DNS Records Required

In Cloudflare DNS for `scitex.ai`, add CNAME records pointing to the tunnel:

- `orochi` -> (already exists)
- `ws.orochi` -> tunnel CNAME
- `orochi-dev` -> tunnel CNAME
- `ws-dev.orochi` -> tunnel CNAME

## Notes

- WebSocket connections through Cloudflare tunnels work natively (no special config).
- The dev instance intentionally has Telegram bridge DISABLED to prevent duplicate messages.
- After updating tunnel config, restart cloudflared: `sudo systemctl restart cloudflared`
