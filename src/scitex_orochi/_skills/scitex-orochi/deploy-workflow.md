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

## Post-deploy verification — daphne reload + hash check

Added 2026-04-14 after the `star` fix chain (mamba-scitex-expert-mba msg #10656, mamba-todo-manager msg #10632). **"Committed to develop + `collectstatic` ran" is NOT the same as "deployed"**. A fix can be disk-present but still served stale because daphne has the old mapping in memory.

### The failure mode

On 2026-04-14 the fleet thought `star` was fixed, shipped two commits (explorer-mba `bac1342`, todo-manager `0a442fb`), ran `collectstatic`, and asked ywatanabe to hard-reload. It still didn't work. Root cause (discovered via Playwright + browser devtools):

- Disk: new manifest at `hub/app.68ea5584f68d.js`, template at `?v=124`.
- Cloudflare: `cf-cache-status: DYNAMIC` — not caching, innocent.
- Browser: fetching `app.dc4e19e26b48.js?v=123` — **the old hashed filename**.
- Daphne (PID 1 in the hub container): still holding the old `ManifestStaticFilesStorage` mapping + old compiled template in memory. It served the old filename because its in-memory table never refreshed.

`docker restart orochi-server-stable` fixed it in one command. Every `collectstatic` after-the-fact needs a daphne reload, or the fix is on disk but invisible.

### Required verification sequence

After **any** frontend change that touches hashed static files, templates, or URL routes:

1. **Collectstatic on disk**
   ```bash
   ssh nas 'cd ~/proj/scitex-orochi && docker compose -f docker-compose.stable.yml exec orochi-server python manage.py collectstatic --noinput'
   ```

2. **Daphne reload (mandatory, not optional)**
   ```bash
   ssh nas 'docker restart orochi-server-stable'
   ```
   A `docker compose up -d` with the same image tag does **not** restart daphne — the container decides it is already up-to-date and skips the reload. Use `docker restart` explicitly.

3. **Hash / version check from outside the container** — confirm the running daphne actually serves the new filename:
   ```bash
   curl -sI https://scitex-orochi.com/static/hub/ | head -1     # route answers
   curl -s https://scitex-orochi.com/ | grep -oE 'app\.[a-f0-9]+\.js\?v=[0-9]+'
   # → should print the new hash matching the manifest
   ```
   The assistant doing the deploy must see the new hash with their own eyes, not infer from "the commit landed".

4. **Playwright / browser round-trip** — for any UI change, Playwright (or an equivalent headless browser) fetches the page and asserts the fixed behavior is live. Screenshot attached to the close-evidence. This is the ground truth that the deploy actually reached the user.

5. **Console errors zero** — open devtools (or Playwright's console capture), reload, confirm no `ReferenceError` / `404` / stale-hash errors. A silent `ReferenceError` was the root cause of the initial `star` fix failure (`getCsrfToken is not defined`); console was the one place it was visible.

### Discipline — no "deployed" claims without verification

Before any Orochi chat post claiming "deployed" or "fixed":

- Step 2 (daphne restart) must have completed.
- Step 3 (hash check from outside) must have printed the new hash.
- At least one of step 4 (Playwright) or a real browser reload with visible success was performed.

Claim format:

> `vX.Y.Z deployed ✓ — <feature>. Hash: app.68ea5584f68d.js. <Playwright screenshot>.`

"Deployed" without the hash and a screenshot is a discipline violation and the auditor should reopen the corresponding issue.

### When `docker compose up -d` *is* enough

If the deploy involves rebuilding the image (`docker compose build`), then `up -d` with the new image tag triggers a genuine container recreate, and daphne starts fresh. In that path the explicit `docker restart` is not strictly necessary — but `up -d` without a rebuild is the common trap. Rule of thumb: **whenever collectstatic ran against the *running* container, assume daphne reload is required**.

### Cross-reference

- `close-evidence-gate.md` — close-evidence must include the hash + screenshot, this discipline is the mechanism that makes those artifacts truthful
- mamba-scitex-expert-mba msg #10656 — walkthrough of the actual incident
- mamba-todo-manager msg #10632 — the failure mode and the fix

## Data Persistence

Media files must survive container rebuilds. The Docker volume mount ensures this:

```yaml
volumes:
  - /data/orochi-media/:/app/media/
  - /data/orochi-stable/:/data/
```
