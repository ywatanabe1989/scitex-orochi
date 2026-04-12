# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.10.6] - 2026-04-13

### 🚀 Features
- feat(hub/voice): mic + language are now a unified split-button
  (`<span class="voice-split">`) — mic on the left, language pill on
  the right, sharing one visual unit so the language indicator is
  always visible. msg#6533.
- feat(hub/voice): persist last-used language across sessions via
  `localStorage["orochi-voice-lang"]`. Falls back to the browser
  locale on first use. msg#6528.

### 🐛 Bug Fixes
- fix(hub/voice): clicking the mic button (or its language pill) now
  immediately hands focus back to `#msg-input`, so the next Enter
  goes to sendMessage instead of re-toggling the mic. The buttons
  also gain `tabindex="-1"` so keyboard navigation never lands on
  them. msg#6537 — ywatanabe pressed Enter expecting send, hit the
  mic toggle instead.

## [0.10.5] - 2026-04-13

### 🚀 Features
- feat(hub/voice): right-click the mic button to cycle language
  (EN ↔ JA), keyboard shortcuts to toggle the mic without touching
  the mouse (`Ctrl+M` cross-platform, `Alt+V` macOS-friendly backup).
  Hover tooltip now reflects the current language and the shortcut
  hint. ywatanabe at msg#6515 ("右クリックで言語選択") and msg#6516
  ("ショートカットキーがあるとよいね").

## [0.10.4] - 2026-04-13

### 🐛 Bug Fixes
- fix(hub/voice): hands-free dictation now works across multiple sends.
  Before: with the mic on (continuous=true), sending a message cleared
  the textarea but the next recognition.result event re-rendered the
  full session transcript on top of the now-empty input, accumulating
  forever. After: chat.js sendMessage calls a new
  `window.voiceInputResetAfterSend()` exported by voice-input.js which
  resets baseText AND restarts the recognition session so the input
  stays clean. ywatanabe at msg#6500 / msg#6504 / msg#6506: "もう喋り
  っぱなしで行けるようになるとめっちゃ嬉しいです" — voice button no
  longer needs to be re-clicked between messages.

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
