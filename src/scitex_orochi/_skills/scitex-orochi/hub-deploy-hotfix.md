---
name: orochi-hub-deploy-hotfix
description: How to hot-deploy code changes to the running Orochi hub Docker container without full rebuild.
---

# Hub Deploy Hotfix

Use this procedure when you need to push a small fix to production quickly without waiting for a full Docker image rebuild.

**Warning**: `docker restart` drops all WebSocket connections. Agents reconnect automatically within ~3 seconds via their built-in reconnect loop. Brief message loss is possible during the restart window — this is acceptable for a hotfix.

## Change Type Decision Tree

```
Did you change a static file (.js, .css) or HTML template?
  YES → collectstatic + docker restart (Section A)
  NO  → Did you change Python code (.py)?
          YES → docker restart only (Section B)
          NO  → No restart needed
```

## Section A — Static / Template Changes

Static files are served through `ManifestStaticFilesStorage`. This rewrites filenames to include a content hash (e.g., `app.68ea5584f68d.js`). Daphne holds the filename→hash mapping **in memory** at startup. Running `collectstatic` writes new files to disk but the running Daphne process never sees the update — it keeps serving the old hash until restarted.

**Full command sequence**:

```bash
# 1. Pull the latest code onto MBA
cd ~/proj/scitex-orochi
git pull origin develop          # or the feature branch

# 2. Copy changed files into the running container
docker cp src/scitex_orochi/hub/static/ orochi-server-stable:/app/src/scitex_orochi/hub/static/
docker cp src/scitex_orochi/hub/templates/ orochi-server-stable:/app/src/scitex_orochi/hub/templates/

# 3. Run collectstatic inside the container
ssh nas 'docker exec orochi-server-stable python manage.py collectstatic --noinput'

# 4. Restart Daphne (mandatory — in-memory hash table must refresh)
ssh nas 'docker restart orochi-server-stable'

# 5. Verify the new hash is live
curl -s https://scitex-orochi.com/ | grep -oE 'app\.[a-f0-9]+\.js\?v=[0-9]+'
# Must print the new hash, not the old one
```

**Why `docker compose up -d` is not enough**: if the image tag hasn't changed, Docker decides the container is already up-to-date and skips the restart. Use `docker restart <container-name>` explicitly after `collectstatic`.

## Section B — Python Code Changes

Changes to `consumers.py`, `views.py`, `models.py`, routing, etc. do not involve static file hashes. Daphne loads Python modules at startup; a restart picks up the new code.

**Full command sequence**:

```bash
# 1. Pull the latest code on MBA
cd ~/proj/scitex-orochi
git pull origin develop

# 2. Copy changed Python files into the container
# Example: consumers.py change
docker cp src/scitex_orochi/hub/consumers.py orochi-server-stable:/app/src/scitex_orochi/hub/consumers.py

# 3. Restart Daphne
ssh nas 'docker restart orochi-server-stable'

# 4. Verify
ssh nas 'docker logs orochi-server-stable --tail 30'
# Should show clean startup, no tracebacks
```

For Django model changes that require migrations:

```bash
ssh nas 'docker exec orochi-server-stable python manage.py migrate'
ssh nas 'docker restart orochi-server-stable'
```

## Verification After Any Hotfix

Run all four checks before claiming "deployed":

```bash
# 1. HTTP health
curl -sI https://scitex-orochi.com/api/health/
# → HTTP/2 200

# 2. Static hash check (for static/template changes)
curl -s https://scitex-orochi.com/ | grep -oE 'app\.[a-f0-9]+\.js\?v=[0-9]+'
# → new hash e.g. app.68ea5584f68d.js?v=124

# 3. Docker logs clean
ssh nas 'docker logs orochi-server-stable --tail 20'
# → no ERROR or traceback lines

# 4. Agents reconnected
curl -s https://scitex-orochi.com/api/agents/ | python3 -m json.tool | grep -c '"status": "online"'
# → count matches expected number of live agents
```

Only post "deployed" after all four pass.

## Claim Format

> `hotfix deployed — <description>. Hash: app.<hash>.js?v=<ver>. Agents: <N> online.`

## git pull → docker cp Pattern

The `git pull + docker cp` pattern is the correct hotfix approach. Avoid these alternatives:

- **Do not** `git pull` inside the container — the container may not have git configured with the right SSH keys.
- **Do not** volume-mount the source directory for production — it bypasses the image's installed package structure.
- **Do not** rebuild the image for a hotfix — too slow (minutes vs. seconds).

## Cross-Reference

- `deploy-workflow.md` — full release process with version bump, tag, and GitHub release
- `hub-stability.md` — what to do when the hub is unreachable before you can hotfix
- `close-evidence-gate.md` — evidence requirements when closing issues fixed by a hotfix
