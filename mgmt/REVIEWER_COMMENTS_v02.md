# Reviewer Comments v02 — scitex-orochi audit (2026-04-27)

Read-only audit of the post-0.15.5 develop branch. Findings below are
sorted by severity within each axis; the worst items appear first
overall.

## 1. Security

### CRITICAL — `_redact_env_line` has multiple secret-leak bypasses
File: `scripts/client/_collect_agent_metadata/_files.py:196-213`. The
"long opaque token" heuristic is `len(v)>=24 and
v.replace('-','').replace('_','').replace('.','').isalnum()`. It fails
to redact:

- Quoted values (`FOO="..."`): the leading `"` makes `isalnum()` False
  on the joined string, so the value is returned verbatim.
- DSN / URL secrets: `DATABASE_URL=postgres://u:hunter2@host/db`,
  `REDIS_URL=...` — `:`, `/`, `@` defeat the alnum check, and the key
  matches none of `TOKEN/SECRET/KEY/PASSWORD/PASS/CREDENTIAL`.
- Standard base64 (`+`, `/`, `=` padding) — same alnum failure.
- Multi-line PEM / JSON values: only the first KEY=line is examined;
  continuation lines have no `=` and return unchanged
  (`return line` at L201).
- Hub-side `redact_secrets` (`hub/views/agent_detail.py:71-91`) is
  applied to `orochi_env_file` (L272) but its regex set covers only
  `sk-ant`, `gh[pousr]_`, JWT, AWS AKIA, bearer, and a `password[:=]`
  pattern — it does NOT catch DSN-shaped credentials either. Both
  layers fail open on `DATABASE_URL`/`SENTRY_DSN`/`AMQP_URL`.

Severity: critical because the .env viewer is now an exposed UI
surface; a single leaked DB URL is full game-over.

Fix in one sentence: replace the alnum heuristic with an explicit
allowlist of safe-to-show keys (and add patterns for `://`, `@`,
base64, and quoted values; drop multi-line values entirely or redact
any line not matching `^[A-Z_][A-Z0-9_]*=` after the first `=` line).

### IMPORTANT — Substring key-match over-redacts and under-redacts
File: `_files.py:204-208`. Substring `KEY` matches `MONKEY`,
`KEYBASE_USER`, `LOCALE_KEYBOARD` (over-redaction nit, but breaks
ops); and `DSN`, `URL`, `WEBHOOK`, `CONNECTION_STRING`,
`SLACK_HOOK` are not flagged. Use word-boundary or suffix checks
(`.endswith(("_TOKEN","_SECRET","_KEY","_PASSWORD"))`).

### IMPORTANT — `csrf_exempt` register endpoint trusts token from query/body
File: `hub/views/api/_agents_register.py:11`. Token can arrive in
`?token=` (query string) — these end up in webserver access logs and
referer headers. Severity important because logs are a real exfil
path.

Fix: require the token in the JSON body or `Authorization: Bearer`
header; reject `?token=`.

### NIT — Frontend escaping in `agents-tab/detail.ts` is consistent
File `hub/frontend/src/agents-tab/detail.ts` — all agent-pushed
strings (`claudeMd`, `mcpJson`, `pane_text`, `envText`, `channels`,
`name`) are wrapped in `escapeHtml()` (L209-452). No unsafe
interpolation found. Pass.

## 2. Consistency

### PASS — Version
`pyproject.toml:3` = `0.15.5`, `src/scitex_orochi/__init__.py:3` =
`0.15.5`, `orochi/settings.py::_dynamic_version()` reads env first
then file. Aligned.

### PASS — Naming migration
Grep for unprefixed `pane_state`/`comm_state`/`active_task_count` in
`hub/` returns no hits; `agent_meta.py` is now only mentioned in
docstrings/comments referring to the legacy name (intentional).

### NIT — Stale comments still reference `agent_meta.py`
`hub/registry/_register.py`, `_payload.py`, multiple `*.ts`,
`hub/quota_watch.py`. Not bugs, but search/replace target.

## 3. Oversized files

- Top app source files (excl. node_modules): `hub/auto_dispatch.py`
  (791), `hub/registry/_register.py` (742),
  `hub/tests/test_auto_dispatch.py` (709), TS:
  `activity-tab/compose.ts` (691), `tabs.ts` (673), `agents-tab/detail.ts`
  (632). Memory-cited 3000+-line monsters are gone — refactor landed.
- `auto_dispatch.py:1-791` is the new ceiling and is a candidate for
  splitting (severity: nit).

## 4. Tests

### IMPORTANT — No tests for `_redact_env_line` or `_files.py`
No `test_*files*` / `test_*env*` / `test_*redact*` under
`scripts/client/`. The hub-side `redact_secrets` is tested
(`hub/tests/views/api/test_agent_detail.py:171-180`) but only against
a single short example. Given the bypass bugs above, this is the
single highest-leverage test gap.

Fix: add a parametrized test with the bypass cases listed in §1
(quoted, DSN, base64, multi-line PEM).

### PASS-ish — Heartbeat + agent_detail covered
`test_agents_register.py`, `test_heartbeat.py`,
`test_agent_detail.py` (auth, missing agent, redact, full-pane,
ping/pong) — coverage of happy + auth-rejection paths exists.

## 5. Frontend

### IMPORTANT — Dead classic-script .js files
`hub/static/hub/` has 32 standalone `.js` files (e.g.
`agent-badge.js`, `dms.js`, `init.js`, `agents-tab/{controls,detail,
lamps,overview,state}.js`). `dashboard.html:540` loads only the Vite
bundle; **zero** `<script src="{% static 'hub/...">` references the
classic scripts in dashboard.html. They are dead and were the source
of "edited the wrong file" thrash this session.

Fix: `git rm hub/static/hub/{agents-tab,*.js}` (keep the
`hub/static/hub/app/` files still referenced by
`workspace_settings.html:400-410`).

### NIT — Bundle size
`hub/static/hub/dist/orochi-BW4E-eFV.js` = 771 KB; largest src dirs
are `activity-tab/` (368 KB), `app/` (212 KB), `chat/` (108 KB).
Mermaid + highlight.js are external CDN, so the 771 KB is genuinely
app code. Worth a `vite-bundle-visualizer` pass; not urgent.

### IMPORTANT — CSS cascade traps similar to `.avatar-clickable`
This audit did not exhaustively grep all `display:` rules but the
just-fixed `display:inline-flex` from `.avatar-clickable` setting on
a `<td>` (`6cbdeb`, `623c021`) suggests an audit pass: any class that
sets `display:` and is also used inside `<table>`, `<tr>`, `<td>`,
or grid containers. Recommend a targeted lint rule.

## 6. Deploy / ops

### IMPORTANT — Two cloudflared connectors run concurrently
Memory cites `c1fddc4d` (mba) + `bc461e9d` (ywata-note-win). Neither
is documented in `deployment/README.md`. The active prod is
ambiguous; `Makefile:100` hard-pins `PROD_HOST := mba`. Resolve which
tunnel is authoritative and document the other as standby (or retire
it). The "prod host can be mba OR ywata-note-win" memory is now a
silent foot-gun.

### PASS — Caffeinate plist discoverable
`deployment/README.md:45` and
`deployment/host-setup/launchd/README.md:96-126` both reference
`com.ywatanabe.colima-caffeinate.plist` and the install script.

## 7. Open PRs / branches

### IMPORTANT — 84 local branches, ~22 fully merged into develop
`git branch --merged develop` shows ~22 stale feature branches
(`feat/255-singleton-enforce-v2`, `fix/256-dashboard-uses-hostname`,
`feature/django-rewrite`, ...). Cruft accumulating.

### NIT — Open PRs
10+ open PRs in this repo, several from 2026-04-14 to -17 with no
recent activity (#190, #189, #163, #146). Triage pass needed.

## 8. Latent regressions to suspect

- The .env redaction bypasses (§1) are the obvious next "looked
  working in dev, leaked in prod" candidate. Treat as urgent.
- The 2-tunnel cloudflared situation (§6) is the same shape as the
  colima App-Nap latent flake — runs fine until it doesn't, no
  observability.
- `pane_text_full` (10 KB cap, `_files.py:230` and ditto for
  CLAUDE.md/.mcp.json) — the 10 KB hard truncation can split a JSON
  value or a markdown fence; consumers re-parse via `JSON.parse`
  defensively but truncation is silent.

## 9. Documentation

- `infra-hub-stability.md` updated. The `deployment/README.md` (L63)
  cross-links it, but `deployment/host-setup/launchd/README.md` does
  NOT cross-link `infra-hub-stability.md` — operators reading the
  caffeinate doc miss the broader story.
- Top-level `README.md` was last touched 2026-04-20, predates
  0.15.5 — not stale by version (no version embedded), but mention
  of "Django Channels" appears only at L179 — fine.

## Overall assessment

Code quality is solid post-refactor: large monoliths decomposed,
prefix-naming migration completed, bundle migration to Vite is
clean, escapeHtml usage is disciplined, and the agent_detail unit
tests pin shape and auth. The .env viewer feature is the dominant
risk: producer-side redaction is a heuristic that fails on the most
common production secret shapes (DSNs, quoted values, multi-line
keys), and the hub-side regex set does not save it. This is an
architectural defect, not a polish item.

### Rating: 6 / 10
### Determination: REJECT (revise-and-resubmit)

Acceptance is contingent on fixing the §1 critical (env redaction)
plus adding the parametrized bypass test from §4.

## Do-next (impact / effort)

1. **Rewrite `_redact_env_line`** with allowlist + DSN/URL/multiline
   handling; mirror in `hub/views/agent_detail.py::redact_secrets`.
   Add parametrized test with quoted/DSN/PEM/base64 cases. (high / low)
2. **Delete `hub/static/hub/{agents-tab/,*.js}`** (32 dead files) to
   eliminate the wrong-file-edit class. (high / trivial)
3. **Document or retire** the second cloudflared connector;
   put canonical prod host in `deployment/README.md`. (high / low)
4. **Reject `?token=`** for `api_agents_register`; require
   body or `Authorization` header. (medium / low)
5. **Branch hygiene**: `git branch --merged develop | xargs -n1 git
   branch -d` after PR-state confirmation. (low / trivial)
