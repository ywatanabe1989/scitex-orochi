# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.10.3] - 2026-04-13

### 🐛 Bug Fixes
- fix(hub/upload): /api/upload-base64 now creates a Message row carrying
  the upload as `metadata.attachments` when the caller passes `channel`
  and `sender`. The Files tab (`api_media`) only reads attachments from
  Message metadata, so MCP `upload_media` calls used to land on disk but
  never appear in the dashboard. Reported by ywatanabe at msg#6425. The
  bun `handleUploadMedia` now passes both fields automatically.
- feat(hub/ui): rich inline thumbnails for non-image attachments — PDF
  cards open in the in-app modal viewer (todo#240 reuse), markdown / text
  files render a fetched first-1200-char preview card, video and audio
  attachments embed inline `<video>` / `<audio>` players. Replaces the
  generic paperclip-link fallback for the common cases. Requested by
  ywatanabe at msg#6423.

## [0.10.2] - 2026-04-13

### 🐛 Bug Fixes
- fix(hub/ui): systemic focus-theft guard for #msg-input — single delegated
  capture-phase mousedown handler on document blocks default focus shift
  whenever the user clicks any `<button>` or `<a>` inside `#messages`,
  `.msg`, or `.thread-panel` while the compose textarea has focus. Replaces
  the per-element fixes that only patched `.msg-fold-btn` in 0.10.1; the
  blur log analysis at msg#6341 (todo#225 reopen) exposed five more
  offenders (`.msg-thread-btn`, `.chat-link`, `.issue-link`, `.permalink-btn`,
  `.thread-permalink-btn`) and a futureproof fix is now in place.

## [0.9.0] - 2026-04-12

### 🚀 Features
- feat: Agents tab heartbeat with subagent count, current task, context % (#19)
- feat: multi-image grid layout for messages (#65)
- feat: auto-link `owner/repo#N` references with inline title injection (#192)
- feat: GitHub webhook receiver endpoint (#63)
- feat: MCP sidecar `agent_meta.py` integration for live Claude Code metadata
- feat: enhanced Agents tab metadata (Mux, Uptime, liveness colors)

### 🐛 Bug Fixes
- fix: thread panel back button on mobile (#58)
- fix: reactions MCP API on bare domain (was 404) (#27)
- fix: mobile input area more compact + sticky tab bar (#195, #196)
- fix: media serving on bare domain (urls_bare.py was missing routes)
- fix: media files persistence (MEDIA_ROOT → /data/media)
- fix: stale agent auto-eviction from dashboard (#35)
- fix: thread reply delivery to agents (#38)
- fix: send button mobile Safari behavior (#52)
- fix: preserve textarea content when new messages arrive (#50)

### 🛠 Improvements
- improvement: compact mobile chat spacing — ~30% less wasted space (#53)
- improvement: TODO tab full issue body inline (#23)

### 🔧 Internal
- chore: add basic CI workflow (pytest + ruff) (#64)
- chore: websockets added to dev deps for CI

[0.9.0]: https://github.com/ywatanabe1989/scitex-orochi/compare/v0.8.0...v0.9.0

## [0.8.0] - 2026-04-12

### Features
- feat: enhanced Agents tab with metadata (mux, uptime, liveness)
- feat: TODO tab shows full issue body inline (#23)
- feat: PWA support + iPhone SE responsive design (#47, #48)
- feat: message edit/delete CRUD operations (#34)

### Fixes
- fix: media download HTTP 400 (#31, #32, #33)
- fix: stale/renamed agents auto-eviction (#35)
- fix: thread reply delivery (#38)
- fix: @mention autocomplete in reply (#37)

## [0.7.0] - 2026-04-12

### Features
- feat: dual bastion SSH mesh (bastion.scitex.ai + bastion.scitex-orochi.com)
- feat: agent prompt auto-suppression via settings.local.json (#15, #36)

### Fixes
- fix: Python 3.11.3 module load on spartan
- fix: clean up b1/b2 decommissioned bastion references
