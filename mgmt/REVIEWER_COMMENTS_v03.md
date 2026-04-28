# Reviewer Comments v03 — scitex-orochi re-audit (2026-04-27, v0.15.7)

Read-only re-audit verifying the v02 findings were actually closed.

## Verification of v02 findings

- [x] **§1 CRITICAL — `.env` redaction rewrite.** CLOSED.
  Proof: `scripts/client/_collect_agent_metadata/_files.py:196-412` now
  uses suffix allowlist (`_SENSITIVE_KEY_SUFFIXES`) + exact-match set,
  DSN userinfo regex (L237), `detect-secrets` vendor plugins
  (L266-309), narrow high-entropy fallback (L312-340), PEM block
  stripping (L393-412), and explicit redaction of `=`-less
  continuation lines (L364-366). Hub-side mirror at
  `hub/views/agent_detail.py:40-71` adds the `url-userinfo` pattern.
  `pytest tests/test_env_redaction.py -v` → **18 passed, 1 skipped**
  (the skipped one needs `DJANGO_SETTINGS_MODULE`; covered separately
  in `hub/tests/views/api/test_agent_detail.py`).

- [x] **§1 IMPORTANT — `?token=` rejected.** CLOSED.
  `_agents_register.py:48-58` returns 400 with explicit log/Referer
  rationale. Live probe of
  `https://scitex-lab.scitex-orochi.com/api/agents/register/?token=x`
  → **HTTP 400** (matches spec).

- [x] **§5 IMPORTANT — dead `.js` files purged.** CLOSED.
  `find hub/static/hub -name '*.js' -not -path '*/dist/*' | wc -l`
  = **15** (was 99). Templates only reference files that still exist
  (`workspace_settings.html:400-412`, `signup.html:140`).

- [x] **§6 IMPORTANT — cloudflared docs.** CLOSED.
  `deployment/README.md:60-93` documents both tunnel UUIDs with
  canonical/standby roles, the failover runbook, and the
  `cloudflared_tunnel_total_requests` probe.

- [x] **§7 IMPORTANT — branch hygiene.** CLOSED.
  `git branch --merged develop | wc -l` = **7** (was 35); residue is
  worktree branches that auto-prune on cleanup.

## New / still-outstanding findings

### A. CSS cascade traps (§5 v02 follow-up) — PASS-with-residual-risk
Cross-product of "class sets `display: flex|grid|inline-flex|inline-block`
× class used inside `<td>`" yielded **zero new collisions**. The
`avatar-clickable`/`agent-icon-cell` fix at
`components-agent-cards.css:325-329` includes the doc comment
explaining the trap. Severity: nit. **Suggested fix**: add a CSS
linter rule (e.g., a `stylelint` plugin or a `make` target) to fail
CI when a class with `display: !table-cell` is referenced from a
`<td>`. Without automation this category will reopen on the next
agents-tab refactor.

### B. Open PRs / triage — IMPORTANT (unchanged from v02)
20 open PRs; 16 of them have `updatedAt < 2026-04-18` (>9 days
stale): #84, #100, #101, #117, #118, #121, #122, #124, #125, #127,
#146, #163, #189, #190, #192, #194, #195, #326, #340, #347.
**Suggested fix**: a single-pass `gh pr close` sweep on anything
already superseded; rebase or close the rest with a comment.

### C. Hub-side `redact_secrets` test gap — IMPORTANT
`hub/tests/views/api/test_agent_detail.py` is now 279 lines / 12 test
functions (was the single sk-ant case). However, the new
`url-userinfo` pattern at `agent_detail.py:67-70` has **no
hub-side test** — `tests/test_env_redaction.py:153-179` mirrors the
DSN cases but is `pytest.skip`ped without `DJANGO_SETTINGS_MODULE`.
The producer-side test passes; the hub-side is unverified at CI.
**Suggested fix**: add `def test_redact_secrets_dsn_userinfo` to
`hub/tests/views/api/test_agent_detail.py` so the Django test runner
exercises it.

### D. `register_agent` body-vs-Authorization auth path — IMPORTANT
`_agents_register.py:33-60` now has three auth paths (body /
Authorization / reject ?token=). I see no `tests/test_*register*.py`
case for the Authorization-Bearer happy path nor for the
empty-Authorization fallback to body. **Suggested fix**: parametrize
`hub/tests/test_agents_register.py` with `(body, header) ∈
{(t,_), (_,Bearer t), (t,Bearer t2)}` and `?token=t` → 400.

### E. Pane / file truncation at `[:10000]` — NIT (severity downgraded)
`_files.py:143` (CLAUDE.md), `:159` (.mcp.json), `:428` (.env). All
truncate **after** redaction, so a hidden secret can't survive
truncation, but a long JSON/markdown value at the tail is still cut
mid-token silently. Real-world severity is low because consumers
re-parse defensively (`JSON.parse` try/catch in TS), but emitting
`"…(truncated)"` instead of a hard cut would aid debugging.

### F. NEW — `_redact_env_line` minor residual gap
A non-suffix key holding a space-bearing secret like
`INTERNAL_NOTE=admin password is hunter2 do not share` will not be
redacted (no `_PASSWORD` suffix, no DSN, no high-entropy/JWT/hex
shape, contains spaces so base64 regex fails). Severity: nit
(adversarial input only — anyone deliberately writing this is past
the threat model). **Suggested fix**: add a plain-text "password is X"
case to the hub-side `_SECRET_PATTERNS` mirror.

## Overall assessment

The §1 critical and all four §1-§7 important items are genuinely
closed in code, not just claimed-closed. The producer-side redaction
is now defense-in-depth (suffix → DSN → vendor catalog → entropy
fallback → PEM block stripping → continuation-line catch-all) and
its test pack pins the v02 bypass cases. Branch hygiene and dead-JS
cleanup are visible in the git log. The cloudflared doc table is
present and operational.

Residual gaps are tests-of-tests (C, D), PR triage (B), CSS-lint
automation (A), and one edge-case nit (F). None block ship.

### Rating: 8 / 10 (was 6/10)
### Determination: ACCEPT (with minor revisions B, C, D)

## Do-next (impact / effort)

1. Add hub-side DSN test in `hub/tests/views/api/test_agent_detail.py`
   so CI guards the `url-userinfo` pattern. (high / trivial)
2. Parametrize `test_agents_register.py` for body / Authorization /
   ?token= matrix. (high / low)
3. PR triage sweep — close or rebase the 16 stale PRs in one pass.
   (medium / low)
4. Add stylelint rule "no `display: !table-cell` on td-used class"
   to prevent the avatar-clickable family of bugs. (medium / medium)
5. Replace `[:10000]` hard cuts with `…(truncated N chars)` marker
   on CLAUDE.md / .mcp.json / .env collectors. (low / trivial)
