# Hub Docker Deploy — mba stdin-pipe workaround

The scitex-orochi dashboard runs as `orochi-server-stable` in colima on
**mba**. Normal deploy (`docker compose -f deployment/docker/docker-compose.stable.yml up -d --build --force-recreate`) often fails with
"No space left on device" because:

- mba's host `/Users` runs at ~100% capacity
- colima's VM disk (`~/.colima/_lima/_disks/colima/datadisk`) is a
  sparse 100 GiB preallocated file; `docker image prune` frees blocks
  **inside** the VM but does NOT return them to the host.
  `fstrim` reclaims only ~300 MiB in practice.

## Canonical deploy (when disk is healthy)

```bash
ssh mba 'export PATH=/opt/homebrew/bin:$PATH && \
         git -C ~/proj/scitex-orochi fetch origin main --quiet && \
         git -C ~/proj/scitex-orochi reset --hard origin/main && \
         cd ~/proj/scitex-orochi/deployment/docker && \
         docker compose -f docker-compose.stable.yml up -d --build --force-recreate'
```

## Hotpatch deploy (disk full — preferred fallback)

Bypass the host disk entirely: pipe the patched file through SSH into
the running container's overlay, then restart + purge Cloudflare.

### One file

```bash
cat /home/ywatanabe/proj/scitex-orochi/hub/static/hub/app.js \
  | ssh mba 'export PATH=/opt/homebrew/bin:$PATH && \
    docker exec -i orochi-server-stable bash -c "cat > /app/hub/static/hub/app.js && \
    cp -f /app/hub/static/hub/app.js /app/staticfiles/hub/app.js && \
    md5sum /app/staticfiles/hub/app.js"'
```

Always pipe to BOTH paths:
- `/app/hub/static/hub/<file>` — Django `STATICFILES_DIRS` source
- `/app/staticfiles/hub/<file>` — `collectstatic` output served by WhiteNoise

Copy one to the other with `cp -f` (NOT plain `cp`; the
pre-tool-use hook blocks interactive-prompting `cp`).

### Restart container + purge Cloudflare

```bash
ssh mba 'export PATH=/opt/homebrew/bin:$PATH && docker restart orochi-server-stable'
sleep 5

curl -sS -X POST "https://api.cloudflare.com/client/v4/zones/2eda29d603d74180011e6711ffff65a3/purge_cache" \
  -H "X-Auth-Email: $SCITEX_CLOUDFLARE_EMAIL" \
  -H "X-Auth-Key: $SCITEX_CLOUDFLARE_API_KEY" \
  -H "Content-Type: application/json" \
  --data '{"purge_everything":true}'
```

### Verify

```bash
curl -sL "https://scitex-lab.scitex-orochi.com/static/hub/app.js?v=<N>" -o /tmp/live.js
md5sum /tmp/live.js /home/ywatanabe/proj/scitex-orochi/hub/static/hub/app.js
# md5s must match
```

## Why docker exec -i works when scp fails

- `scp mba:/Users/...` writes to the host filesystem, which is 100% full.
- `docker exec -i bash -c "cat > /app/..."` writes into the container
  writable layer under `/var/lib/docker`, which sits in the **colima
  VM's** filesystem. The VM has plenty of free blocks inside its
  sparse 100 GiB disk; it just can't grow the host file further.

## When to use each

| path | disk cost on host | downtime | use case |
| --- | --- | --- | --- |
| `docker compose up --build` | ~1 GiB temp layers | ~30 s | host disk healthy |
| `scp + docker cp` | ~file size | ~2 s | host has ≥1 GiB free |
| **stdin pipe + docker exec tee** | **0** | **~2 s** | host at 100% |

## Proper fix (when you can schedule downtime)

```bash
ssh mba 'export PATH=/opt/homebrew/bin:$PATH && \
         docker stop orochi-server-stable && \
         colima stop && \
         colima delete && \
         colima start --cpu 4 --memory 8 --disk 40 && \
         cd ~/proj/scitex-orochi/deployment/docker && \
         docker compose -f docker-compose.stable.yml up -d --build'
```

This shrinks the colima VM disk from 100 GiB to 40 GiB (adjust as
needed) and rebuilds the image from scratch. Takes
`orochi-server-stable` down for several minutes.

## Cloudflare credentials

Env vars on the deploying machine:
- `SCITEX_CLOUDFLARE_EMAIL=admin@scitex.ai`
- `SCITEX_CLOUDFLARE_API_KEY` (Global API Key)

Zone ID for `scitex-orochi.com`: `2eda29d603d74180011e6711ffff65a3`.
