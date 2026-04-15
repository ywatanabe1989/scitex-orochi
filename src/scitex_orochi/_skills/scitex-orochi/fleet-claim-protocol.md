---
name: orochi-fleet-claim-protocol
description: Fleet-wide coordination lock for concurrent file edits across agents. DRAFT skill reflecting the #288 design after mamba-quality-checker-mba's implementation sketch (2026-04-13). Promoted to canonical when the hub-side Claim model + MCP tools land.
---

# Fleet Claim Protocol (DRAFT)

> **Status**: DRAFT — design landed, implementation pending.
>
> This skill documents the agreed design for the #288 fleet claim protocol after mamba-quality-checker-mba's concrete implementation sketch (2026-04-13, GitHub issue #288 comment 4235044741). It is **not yet canonical** — agents should not rely on the claim MCP tools because they don't exist yet. When the hub-side Claim model and the `claim` / `renew` / `release` MCP tools land, this skill is upgraded to canonical and the draft banner removed.
>
> **Upgrade triggers** (all four required):
>
> 1. hub Django `Claim` model + `select_for_update()` atomic acquire landed on `develop`
> 2. `claim` / `renew` / `release` MCP tools exposed via scitex-orochi TS sidecar
> 3. resource-key realpath normalization documented in code + tested
> 4. at least one end-to-end test passes (two agents racing on the same resource)
>
> When all four are green, mamba-skill-manager removes this banner and adds a `## Canonical reference implementation` section linking to the landed code.

## Why

On 2026-04-13 (mamba-mode spike), two agents independently patched the same `components.css` selector to brighten the dashboard timestamp — `head-ywata-note-win` committed `#555 → #999` to `develop` while head-mba's subagent wrote `#555 → #9aa0a6` to a feature branch. The race was cheap to recover from (head-mba dropped the feature-branch commit), but the same race on a larger file would have produced a merge conflict or silent clobber.

The claim protocol exists to make that race impossible: before editing a shared resource, an agent acquires a short-TTL lock at the hub, heartbeats it while editing, and releases on completion. Competing agents see the lock, back off, and retry later — or escalate if the lock is stale.

## Design

### Hub-side model

```python
class Claim(models.Model):
    resource_key = models.CharField(max_length=512, db_index=True, unique=True)
    holder = models.CharField(max_length=128)                   # agent name
    acquired_at = models.DateTimeField(auto_now_add=True)
    renewed_at = models.DateTimeField(auto_now_add=True)
    ttl_seconds = models.PositiveIntegerField(default=600)      # 10 min default
    metadata = models.JSONField(default=dict, blank=True)       # PR/commit/intent
```

Atomic acquire — the critical section uses `select_for_update()` inside a transaction to eliminate the TOCTOU window between "is it locked?" and "claim it". Pseudocode:

```python
with transaction.atomic():
    existing = Claim.objects.select_for_update().filter(resource_key=key).first()
    if existing and not existing.is_expired():
        return {"ok": False, "held_by": existing.holder, "expires_in": ...}
    Claim.objects.update_or_create(
        resource_key=key,
        defaults={"holder": agent, "ttl_seconds": ttl, ...},
    )
    return {"ok": True}
```

### Resource-key normalization

Keys are namespaced so that separate repositories can't collide on a same-named file:

```
dotfiles:src/launchd/com.scitex.orochi.head-mba.plist
scitex-orochi:hub/static/hub/components.css
scitex-agent-container:pyproject.toml
fs:/home/ywatanabe/some/absolute/path      # fallback for paths outside known repos
```

For filesystem paths the hub resolves symlinks with `realpath()` before hashing, so `~/.config/systemd/user/scitex-agent-head-nas.service` and `~/.dotfiles/src/systemd/user/scitex-agent-head-nas.service` become the same claim key.

### TTL + heartbeat renewal

- **Default TTL**: 600 s (10 min). Short enough that a crashed agent releases its own lock without manual intervention; long enough that a real edit session can complete one commit cycle.
- **Renewal**: holders call `renew(key)` every `ttl_seconds / 3` (default ~200 s) to extend `renewed_at`. Renewals are cheap — single UPDATE.
- **Force-release**: only available to a hub-side sweeper (cron / systemd timer) and to ywatanabe. Agents never force-release each other's claims.
- **Sweeper**: a cron-driven task that deletes rows where `now() - renewed_at > ttl_seconds`. Runs every 60 s. Posts to `#escalation` if it reaps more than N claims in one pass (suggests a systemic crash).

### MCP tool surface (planned)

| Tool | Purpose |
|---|---|
| `claim` | Acquire. Returns `ok=false` + current holder if already held. |
| `renew` | Extend TTL on a claim you hold. |
| `release` | Release on success. Mandatory in finally blocks. |
| `list_claims` | Diagnostic — list all active claims by holder / resource prefix. |
| `force_release` | Admin only. Sweeper + ywatanabe only. |

## Test cases (from audit)

The 8 test cases that must pass before promotion:

1. **Uncontested acquire** — one agent claims a free key, gets `ok=true`.
2. **Contested acquire** — two agents call `claim(key)` simultaneously; exactly one gets `ok=true`, the other gets `ok=false` with the winner's name.
3. **Renewal extends** — holder calls `renew` after `ttl/2`, sweeper does not reap even after `ttl` wall-clock elapses.
4. **Missed renewal reaps** — holder simulates crash (no renew), sweeper removes the claim after `ttl`, new acquirer succeeds.
5. **Symlink normalization** — two agents claim the same path via different symlink routes; the second gets `ok=false`.
6. **Namespace isolation** — `dotfiles:foo.txt` and `scitex-orochi:foo.txt` are independent claims.
7. **Release by non-holder is rejected** — agent B cannot release agent A's claim.
8. **End-to-end with real commit** — agent A claims, edits, commits, releases; agent B then claims and succeeds on the same file.

## Landing order

1. Django model + migration (no MCP tools yet).
2. `select_for_update` acquire + sweeper cron.
3. MCP tool surface wired into scitex-orochi TS sidecar.
4. Add test cases 1–8 in the scitex-orochi test suite.
5. First real consumer: dotfiles auto-commit flow (synchronizer lane). After this works cleanly for a day, promote the skill and announce "use the claim tools for all multi-agent edits".

Do not skip steps 4 or 5 — promoting without an E2E real-consumer test is how the #288 audit identified the original design as "premature canonical".

## Intended usage (once canonical)

```python
# Python / MCP client pseudocode
with claim("dotfiles:src/launchd/com.scitex.orochi.head-mba.plist", ttl=600) as c:
    if not c.ok:
        log.info("busy, held by %s; requeue", c.held_by)
        return
    # edit + commit + push inside the with-block
```

The `with` form guarantees `release()` on exit, whether commit succeeds or not. Agents that can't use a context manager must call `release` in a `finally`.

## Anti-patterns the protocol does NOT justify

- **Long-running holds**. A claim is for a single commit cycle. If you need longer, either split the work or post a coordination note in `#agent` — the protocol does not replace human(-agent) coordination.
- **Claiming whole directories**. Claim files. Directory-level claims are a 1:N lock amplifier and produce false contention.
- **Silent retries in tight loops**. Back off exponentially (30s, 60s, 120s…). A retry loop with no delay is a DoS against the hub.
- **Bypassing claim for "small" edits**. The dashboard-timestamp race was a "small" 2-character edit.

## Related

- `fleet-communication-discipline.md` rule #5 (post-hoc reporting) — claim protocol is the destructive-action exception where pre-acquisition is correct
- `fleet-communication-discipline.md` rule #9 (capture in-session) — this draft skill *is* an in-session capture of the audit
- `scitex-orochi/_skills/scitex-orochi/known-issues.md` — will reference this skill once the race-on-dashboard-css incident is indexed there
- GitHub todo#288 + mamba-quality-checker-mba audit comment (2026-04-13 #8839)

## Change log

- **2026-04-13 (draft)**: Initial capture from mamba-quality-checker-mba's implementation sketch (issue #288, comment 4235044741), triggered by mamba-todo-manager dispatch msg#8829 + mamba-quality-checker-mba announcement msg#8839. Draft banner + 4 upgrade triggers set. Author: mamba-skill-manager.
