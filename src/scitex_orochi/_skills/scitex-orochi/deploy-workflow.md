---
name: orochi-deploy-workflow
description: End-to-end deployment process for Orochi hub and agent restart procedures.
---

# Deploy Workflow

## Release Hygiene (Required for Every Deploy)

Every deploy of any Orochi/SciTeX package MUST include:

1. **Version bump** following semver:
   - `patch` (X.Y.**Z**+1) — bug fixes only
   - `minor` (X.**Y**+1.0) — backward-compatible feature additions
   - `major` (**X**+1.0.0) — breaking changes
2. **Git tag** `vX.Y.Z`
3. **GitHub Release** with notes (`gh release create vX.Y.Z --notes ...`)
4. **CHANGELOG.md** update if the package has one

Skipping any of these is a violation of the deploy convention. Tag + release are
how downstream agents and users discover what changed.

```bash
# Reusable post-bump release flow
git tag "v${VERSION}"
git push && git push --tags
gh release create "v${VERSION}" --title "v${VERSION}" --notes-file RELEASE_NOTES.md
```

### Release Notes Format (Required)

Release notes must be human-readable and grouped by change type. Use this
template (matches GitHub Releases conventions):

```markdown
## What's Changed

### 🚀 Features
- feat: short description (#NN)

### 🐛 Bug Fixes
- fix: short description (#NN)

### 🛠 Improvements
- improvement: short description (#NN)

### 📚 Documentation
- docs: short description (#NN)

### 🔧 Internal
- chore: short description
- refactor: short description

**Full Changelog**: https://github.com/<owner>/<repo>/compare/vPREV...vNEW
```

Each repository should also maintain a top-level `CHANGELOG.md` (Keep a
Changelog convention: https://keepachangelog.com) mirroring the same content in
reverse-chronological order so the dashboard's Changelog tab can render it
without hitting the GitHub API.

Empty sections may be omitted, but at least one section must be present.

## Hub Deployment

The Orochi hub runs on NAS via Docker. Production URL: `https://scitex-orochi.com/`

### Steps

1. **Bump version** (on dev machine):

   ```bash
   cd ~/proj/scitex-orochi
   ./scripts/bump-version.sh patch   # or minor, major
   ```

2. **Commit, tag, push, and release**:

   ```bash
   git add -A && git commit -m "chore: bump version to vX.Y.Z"
   git tag vX.Y.Z
   git push origin develop && git push --tags
   gh release create vX.Y.Z --title "vX.Y.Z" --notes "..."
   ```

3. **Pull on NAS**:

   ```bash
   ssh nas 'cd ~/proj/scitex-orochi && git pull'
   ```

4. **Build and restart Docker**:

   ```bash
   ssh nas 'cd ~/proj/scitex-orochi && docker compose -f docker-compose.stable.yml build && docker compose -f docker-compose.stable.yml up -d'
   ```

5. **Purge Cloudflare cache** (cached HTML/JS causes stale dashboard UI).

6. **Verify**:
   - Check `/api/config` shows new version
   - Confirm agents reconnect (check `/api/agents`)
   - Test media uploads (attach/paste/drag-drop)

### Dual Instance Setup

| Instance | Dashboard | WebSocket | Docker Compose |
|----------|-----------|-----------|----------------|
| stable (`orochi.scitex.ai`) | `:8559` | `:9559` | `docker-compose.stable.yml` |
| dev (`orochi-dev.scitex.ai`) | `:8560` | `:9560` | shares stable DB |

Dev connects to stable's WS via `SCITEX_OROCHI_DASHBOARD_WS_UPSTREAM`.

## Agent Restart

### Single Agent

```bash
scitex-orochi restart <agent-name>
# or manually:
scitex-orochi stop <agent-name>
scitex-orochi launch head <agent-name>
```

### All Agents on a Host

SSH to the host and restart each screen session, or use the CLI to iterate:

```bash
for agent in head-mba mamba-mba caduceus-mba; do
    scitex-orochi restart "$agent"
done
```

### Dev Channel Dialog

After restart, agents using `--dangerously-load-development-channels` may get stuck on a TUI confirmation prompt. `scitex-agent-container` handles this automatically via `screen -X stuff`, but if an agent is unresponsive:

```bash
ssh <host> screen -S <agent-name> -X stuff $'\n'
```

## Data Persistence

Media files must survive container rebuilds. The Docker volume mount ensures this:

```yaml
volumes:
  - /data/orochi-media/:/app/media/
  - /data/orochi-stable/:/data/
```
