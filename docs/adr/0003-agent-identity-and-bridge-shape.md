# ADR 0003 — Agent identity, bridge shape, and the ghost-channels field

- **Status**: Proposed (2026-06-01)
- **Owner**: proj-scitex-orochi
- **Reviewers**: lead, operator
- **Supersedes**: none
- **Related**: ADR 0002 (Django "apps and config" standard), PR #439 (sac/orochi boundary line), audit 2026-06-01

## Context

The 2026-06-01 audit of the live source (not the docs) surfaced three
interlocking architectural smells. This ADR records the proposed
direction; it does **not** itself authorise the refactors. Each Phase
below is a follow-up PR.

The shared root cause is a "comms vs execution" boundary that
the README now correctly states (PR #439) but the **data model**
hasn't caught up to: `sac` is the kernel (knows agents + containers +
peers + fleet), `orochi` is the comms shell (channels + messages +
presence + dashboard). The current implementation still treats agent
**identity** as a co-owned concept.

## North star (assumed)

Following operator direction 2026-06-01 (Telegram msg #79):

> **sac is the kernel of truth for who exists and where they run; orochi
> is the projection / shell that owns who-talked-to-whom.**

Every Phase below is consistent with this north star.

---

## Decision 1 — `spec.orochi.channels: []` is a ghost field. **Remove it.**

### Current state

`OrochiSpec.channels: list[str]` is parsed from agent yaml at
`src/scitex_orochi/_agent_container_bridge/spec.py:29,67`. It has three
in-tree consumers:

| Consumer | Effect |
|---|---|
| `_agent_container_bridge/connector.py:206` | Sends `{"channels": [...]}` in the WS register frame |
| `apps/hub/consumers/_agent_handlers.py:19-33` | **Explicitly ignores** the incoming list — comment: *"ignored — accepting them would let any agent opt itself into any channel"*. The server hydrates membership from persisted `ChannelMembership` rows. |
| `src/scitex_orochi/_client.py:55` | Sets `OrochiClient.channels`, used as the **default target** for `client.send()` calls when the caller omits a channel arg. Real, but invisible to operators. |

### Why it's misleading today

`examples/agents/daemon-auditor-haiku.yaml:66-68` is the smoking gun:

```yaml
# Subscribed channels. Keep this in sync with ``orochi.channels``
# above — the env list is the operational source of truth, the
# ``orochi.channels`` list is for sac registration.
AUDITOR_SUBSCRIBE_CHANNELS: "#general,#heads,#ywatanabe"
```

Even on its own terms this comment is false: `orochi.channels` is
**not** "for sac registration" — sac never reads it. The result is a
**triple source of truth** in that single yaml:

1. `spec.orochi.channels` (orochi bridge sends, hub drops)
2. `AUDITOR_SUBSCRIBE_CHANNELS` env var (daemon reads at runtime)
3. The actual `ChannelMembership` rows in the orochi DB (server-authoritative)

### Options considered

1. **Remove the field entirely.** *(Recommended.)*
   The yaml field has no server-side effect today, and the only
   in-process effect (`OrochiClient.channels` default-target) can be
   replaced with an explicit `default_channel: str | None` parameter on
   `OrochiClient.__init__`. Examples + skill 65 lose the misleading
   line. Cost: ~1 PR, mechanical.

2. **Wire it to a real ACL-gated endpoint.**
   `POST /api/registry/agents/<name>/subscriptions` with token auth.
   `connector.py` would call this *before* the WS connect; server
   would consult an ACL (e.g. `ChannelPermission.granted_to_role`) and
   either grant, reject, or queue for human approval. Heavier:
   needs ADR for the ACL shape, REST endpoint, UI for grant/reject, a
   migration for the ACL table. Optional follow-up after Decision 4.

3. **Document-as-local-default.**
   Keep the field but rename it `default_local_channel: str` (one
   string, not a list), narrow contract: "the default `send()` target
   if no channel is specified". This preserves the convenience but
   eliminates the "subscription declaration" interpretation. Cheap; less
   leverage than Option 1.

### Decision

**Option 1: remove.** Same PR removes:

- `OrochiSpec.channels` field (`spec.py:29`)
- `channels` parsing in `load_orochi_spec` (`spec.py:67`)
- `channels = orochi.channels or ["#general"]` line + the
  `channels` key in the register-frame dict (`connector.py:206,288`)
- `channels: list[str] | None = None` from `OrochiClient.__init__`
  (`_client.py:44`), or rename to `default_channel: str | None = None`
- `spec.orochi.channels:` blocks in all example yamls (head-*.yaml,
  master.yaml, telegrammer.yaml, daemon-auditor-haiku.yaml,
  daemon-stale-pr.yaml)
- The "Keep this in sync" comment block in daemon-auditor-haiku.yaml
- Skill `65_agent-deployment-extras.md:138`

Server-side hub behaviour is unchanged (it was already ignoring the
field). Channel subscription remains server-authoritative via the
existing `ChannelMembership` model + dashboard 👁 toggle.

### Blast radius (verified by grep)

| File | Lines | Action |
|---|---|---|
| `src/scitex_orochi/_agent_container_bridge/spec.py` | 29, 67 | remove field + parser branch |
| `src/scitex_orochi/_agent_container_bridge/connector.py` | 206 (and the `channels` key in the register payload around L288) | remove |
| `src/scitex_orochi/_client.py` | 28, 44, 55, 92, 113 | reshape ctor; replace `self.channels[0]` send-default with `self.default_channel` |
| `orochi-config.yaml` | 41, 50, 57 | (fleet-roster file — different concept, *do NOT* touch) |
| `src/scitex_orochi/templates/orochi-config.example.yaml` | 23, 32, 39 | (fleet-roster — leave) |
| `examples/agents/head-deploy.yaml` | 25 (`spec.orochi.channels`) — line 38 is a different `channels:` block, leave | remove L25 |
| `examples/agents/head-mba.yaml` | 24 | remove |
| `examples/agents/head-research.yaml` | 29 | remove |
| `examples/agents/master.yaml` | 20 | remove |
| `examples/agents/head-general.yaml` | 20 | remove |
| `examples/agents/telegrammer.yaml` | 49 | remove |
| `examples/agents/daemon-auditor-haiku.yaml` | 47 + 66-68 comment | remove block + comment |
| `src/scitex_orochi/_skills/scitex-orochi/65_agent-deployment-extras.md` | 138 | remove example line |
| `tests/scitex_orochi/_agent_container_bridge/test_spec.py` | 200 (`test_channels_null_yields_empty_list`) | delete test (field gone) |

`orochi-config.yaml` and the templates use `channels:` at the
fleet-roster level (operator-declared seed channels), which is a
DIFFERENT concept and stays.

---

## Decision 2 — Collapse the 4-store agent identity into 1 + 2 caches.

### Current state (4 stores, no auto-sync)

| Store | Location | Lifetime | Authority |
|---|---|---|---|
| `ContainerAgent` | `apps/hub/models/_agents.py:86` | DB row, REST-CRUD `/api/registry/agents/` | Hub-managed write surface |
| `AgentProfile` | `apps/hub/models/_identity.py:195` | DB row | Dashboard-facing presence (health, last msg, is_hidden) |
| `hub.registry._agents[name]` | `apps/hub/auto_dispatch.py:38-39`, `consumers/_agent_handlers.py:78` | In-memory dict | Live session cache |
| `_state/registry.py` | scitex-agent-container, on dispatcher host | Filesystem (sac) | sac's spec.yaml inventory |

There is **no observable code path** that reconciles sac inventory
against orochi's `AgentProfile` / `ContainerAgent`. The visible
symptom: orochi UI accumulates old contributors that haven't existed
in sac for months (operator complaint, msg #74).

### Proposal

Per the north star, **sac is canonical**. The data flow becomes:

```
  sac filesystem inventory                       (TRUTH)
  ~/.scitex/agent-container/agents/<name>/spec.yaml
              │
              │ daemon (orochi side) periodically:
              │   - list dir, read each spec.orochi section
              │   - for each name: upsert AgentProfile
              │   - any AgentProfile NOT in inventory -> is_hidden=True
              │     (do NOT delete — preserve history of messages)
              ▼
  orochi: AgentProfile (canonical orochi-side identity)
              │
              ├── ContainerAgent → merge into AgentProfile, delete model
              │   (REST `/api/registry/agents/` redirects to AgentProfile shape)
              │
              └── hub.registry._agents[name] → relabel as "session cache",
                  rebuild on hub restart from AgentProfile + live WS map
```

Concrete changes (sketch; each its own PR):

1. **New reconciler daemon** under `src/scitex_orochi/_daemons/_sac_inventory_sync.py`:
   - Reads `~/.scitex/agent-container/agents/*/spec.yaml`
   - For each name: upsert `AgentProfile` (create or refresh metadata)
   - For each `AgentProfile.name` NOT in inventory: set `is_hidden=True`
   - Cron: every 5 min (configurable via `SCITEX_OROCHI_SAC_SYNC_INTERVAL`)
   - Single-host first (the dispatcher); ADR follow-up for multi-host
     fleet inventory.
2. **Deprecate ContainerAgent**: phase migration —
   - PR A: dual-write (existing ContainerAgent CRUD also upserts AgentProfile)
   - PR B: switch readers to AgentProfile
   - PR C: drop ContainerAgent model + migration
3. **Rename `hub.registry._agents[name]`** → `hub.registry._session_cache[name]`
   to reflect its actual lifetime + role.

Operator's "stale contributors" complaint is solved by step 1 alone
(without 2–3). The reconciler is the highest-leverage single change.

### Blast radius (not authoritative — needs Phase-1 PR scoping)

- `apps/hub/models/_agents.py` (ContainerAgent definition + migrations
  0012, 0023 — leave model rows in place, deprecate writes only)
- `apps/hub/views/api/_agents.py` (~30 lines mentioning is_hidden)
- `apps/hub/registry/_payload.py:50, 52, 166` (payload assembly)
- `apps/hub/registry/_agents.py:78` (in-memory map readers)
- New: `src/scitex_orochi/_daemons/_sac_inventory_sync.py` + tests

---

## Decision 3 — The two WS servers + two WS per agent are intentional. Document them.

### Two WS servers (`_main.py:OrochiServer` vs Django ASGI)

- `OrochiServer` (`src/scitex_orochi/_main.py`, aiohttp + websockets,
  ports 9559/8559): started by `scitex-orochi serve`. Standalone,
  no Django, no DB persistence.
- Django ASGI (`apps/hub/` + `config/asgi.py`): production. Started by
  `daphne`/`uvicorn`. Persists to sqlite/postgres.

Both have agent-register code paths because they served different
deployment shapes:
- `OrochiServer` = local dev quickstart, no database, no migrations.
- Django ASGI = production, durable.

### Proposal

Keep both. **Document the line explicitly** in
`docs/architecture.md` and `docs/getting-started.md`. PR #440 already
clarified the README. Recommend renaming the entry point label from
`scitex-orochi serve` to `scitex-orochi serve --standalone` (with a
deprecation period for the bare form), and adding
`scitex-orochi serve --django` as the explicit production form.

### Two WS per agent (connector.py + mcp_channel.ts)

- `connector.py` opens a python-side WS, primarily for python-API
  users (`OrochiClient`, used by `_daemons/_auditor_haiku/`, etc).
- `mcp_channel.ts` (spawned by claude via the MCP config in
  `mcp.py`) opens a separate TS-side WS for claude's MCP push channel.

Different surfaces (python vs claude/MCP); not redundant. Has a
real cost — every agent holds two WS connections to the same hub.

### Proposal

Document the rationale in `docs/architecture.md` ("Why two WS per
agent"). No code change. Track potential consolidation as a future
ADR if presence metrics show the doubled connection count is
operationally painful.

---

## Decision 4 — Formalise the bridge contract.

### Current state (verified by audit)

The SoC seam consists of an undocumented WS register-frame schema +
several shared env vars + several shared filesystem paths, all
duplicated as string literals across both repos:

| Surface | sac side | orochi side | Contract |
|---|---|---|---|
| WS register payload keys | `connector.py:288` writes | `_agent_handlers.py:45-73` reads (`agent_id, project, machine, hostname, orochi_hostname_canonical, role, model, workdir, icon, icon_emoji, icon_text, color, multiplexer, channels, orochi_claude_md, a2a_url`) | None |
| `SAC_HUB_URL` / `SAC_HUB_TOKEN` env | sac `_network/hub_client.py:41-47` reads | orochi `/api/agents/<name>/snapshot[/latest]`, `/owner/` serves | None |
| `SCITEX_AGENT_CONTAINER_YAML_DIRS` env | sac `config/_resolve.py:46-49` reads | orochi skill `83_agent-launch-discipline-spartan.md:46-58` documents | Two docstrings |
| `SCITEX_OROCHI_PUSH_TS` env | (operator only) | orochi `mcp.py:45-49` reads | mcp.py docstring + skill md |
| Hardcoded `mcp__scitex-orochi__*` perm glob | sac `runtimes/settings_json.py:153` | orochi `mcp.py:172` writes the server name `scitex-orochi` | None (string match) |

### Proposal

1. Introduce `docs/contracts/`:
   - `ws-register-frame.schema.json` — JSON Schema for the WS register
     payload. Both sides cite this as the contract.
   - `env-vars.md` — table of every cross-repo env var, owner, format.
   - `paths.md` — table of cross-repo filesystem paths, owner,
     format, lifetime.
2. Make `spec.py:load_orochi_spec` schema-driven (load the JSON
   schema, validate; raise `BridgeContractError` on mismatch).
3. Add a **contract test** in scitex-orochi that fakes a sac
   register-frame from the schema and asserts the hub consumer
   accepts it. Add a mirror test on the sac side (out of scope here;
   handed off to proj-scitex-agent-container).
4. Bump the schema version field on every change; both sides log a
   warning if version mismatch.

This is the same pattern as `scitex-config`'s `local_state` API
(canonical path resolution lives in one place, not duplicated
strings). The seam becomes a real contract, not a coincidence.

---

## sac-side drift (handed off to proj-scitex-agent-container)

These were surfaced by the audit but are outside this agent's write
scope. Routing to proj-scitex-agent-container per lead's a2a:

| File:line | Drift | Fix |
|---|---|---|
| `scitex-agent-container/README.md:274` | "orochi reads sac's on-disk state" — verified false (orochi reads only over the wire). Same vintage as PR #439. | One-line edit aligning with `docs/sac-and-orochi.md:8-12`. |
| `scitex-agent-container/src/scitex_agent_container/runtimes/settings_json.py:25` | docstring says `~/.scitex/orochi/templates/...`; code at L160-162 uses `~/.scitex/agent-container/templates/...`. | Docstring typo fix. |
| `scitex-agent-container/src/scitex_agent_container/cli_pkg/listen_cmds.py:11,200-201` | CLI error points operators to `SAC_OROCHI_SCOPES.md §4.4` — file lives only at `GITIGNORED/.old/`. | Remove pointer or restore doc. |
| `scitex-agent-container/src/scitex_agent_container/runtimes/settings_json.py:153` | Hardcoded `mcp__scitex-orochi__*` permission glob in sac's claude-seed. sac is meant to be orochi-agnostic. | Either move the glob into orochi's bridge (where it would belong) or accept that the seed is a documented per-installation customisation point. |

---

## Phases / sequencing

These are independent unless noted. **None of them is authorised by
this ADR** — each requires its own PR with operator sign-off.

| Phase | Decision | Risk | Effort |
|---|---|---|---|
| 1 | Decision 2 step 1 — sac inventory reconciler daemon | Low (additive) | S |
| 2 | Decision 1 — remove `spec.orochi.channels` | Low–Med (touches yamls; deletes a public-looking field) | S |
| 3 | Decision 4 — `docs/contracts/` + WS register schema + contract test | Med | M |
| 4 | Decision 2 step 2-3 — ContainerAgent → AgentProfile collapse, in-mem map rename | Med–High (model + migrations) | L |
| 5 | Decision 3 — architecture docs | Low | S |
| 6 | sac-side drift cleanup (proj-scitex-agent-container) | Low | S |

## Notes for reviewers

- This ADR records intent. Each Phase is a separate PR with full test
  coverage; the audit-flagged bridge tests landing in
  `test/bridge-soc-seam` cover the seam's *current* shape, and will
  be amended in lockstep with Phases 1–4.
- The "old contributors in orochi UI" symptom is the visible
  consequence of Decision 2 not having been made yet. Phase 1 alone
  resolves it; everything after is hygiene.
- If a Phase exposes a contradiction with the north star (e.g.
  Decision 4 contract work uncovers a sac field orochi MUST
  authoritatively own), file an ADR-amend before that PR opens.
