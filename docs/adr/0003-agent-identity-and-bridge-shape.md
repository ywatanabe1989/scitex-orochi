# ADR 0003 — Agent identity, bridge shape, and the ghost-channels field

- **Status**: Proposed (2026-06-01)
- **Owner**: proj-scitex-orochi
- **Reviewers**: lead, operator
- **Supersedes**: none
- **Related**: ADR 0002 (Django "apps and config" standard), PR #439 (sac/orochi boundary line), audit 2026-06-01, sac-conversation-storage audit 2026-06-01 (operator msg #81)

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
              │   - list dirs under agents/; agent name = directory
              │     name (SAC v3 dir-as-SSoT — no top-level `name:`
              │     field in the spec.yaml itself)
              │   - validate apiVersion == "scitex-agent-container/v3"
              │     and kind ∈ {Agent, AgentProxy}; warn+skip otherwise
              │   - for each valid name: upsert AgentProfile
              │     (create on first sight; never clobber operator-set
              │     icon_emoji/icon_text/color on existing rows — the
              │     only mutation on an existing row is the is_hidden
              │     flag)
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

### AgentProfile keying

The live `AgentProfile` model is composite-keyed —
`unique_together = ("workspace", "name")` (see
`apps/hub/models/_identity.py:234`). The original sketch above framed
this as a flat per-name row; the live schema is more conservative, so
Phase 1 ships under a configurable single-workspace assumption: every
SAC-discovered agent is upserted into one workspace, selected by
`SCITEX_OROCHI_SAC_SYNC_WORKSPACE` (default `"default"`,
get-or-create on first run).

The multi-workspace routing question — "how does a fleet operator
decide which workspace a SAC-discovered agent belongs to?" — is
explicitly out of scope for Phase 1 and tracked as a follow-up ADR.
Two candidate routing strategies for that future ADR:

1. **One workspace per SAC host** (host == workspace). Simple, matches
   operator intuition for multi-host fleets, but conflates the "where
   it runs" and "who can see it" axes.
2. **Workspace selected from `metadata.labels.team`** (SAC v3 field).
   Decouples the two axes; relies on operators populating `team`
   consistently, which today they don't.

Phase 1's single-workspace default neither commits to nor precludes
either strategy.

Concrete changes (sketch; each its own PR):

1. **New reconciler daemon** under `src/scitex_orochi/_daemons/_sac_inventory_sync.py`:
   - Reads `~/.scitex/agent-container/agents/*/spec.yaml` (overridable
     via `SCITEX_AGENT_CONTAINER_AGENTS_DIR`).
   - Agent name is derived from the **directory name** (SAC v3
     dir-as-SSoT: there is no top-level `name:` field in the YAML
     itself; see `scitex-agent-container/examples/agents/full-agent/spec.yaml`
     lines 3-7 for the canonical statement, and
     `_listen/_inline_spec.py:34` for SAC's own validator that
     rejects non-v3 specs).
   - Validates `apiVersion: scitex-agent-container/v3` and
     `kind ∈ {Agent, AgentProxy}`. Non-v3 specs are logged and
     skipped (no AgentProfile row created) — the reconciler echoes
     SAC's own validator contract.
   - For each valid name: upsert `AgentProfile`
     (create-on-first-sight; never clobber operator-set fields like
     `icon_emoji`/`icon_text`/`color` on existing rows — the only
     mutation on an existing row is the `is_hidden` flag).
   - For each `AgentProfile.name` NOT in inventory: set
     `is_hidden=True` (do NOT delete — message history is preserved
     per Decision 2 §1).
   - Tick interval: every 5 min (configurable via
     `SCITEX_OROCHI_SAC_SYNC_INTERVAL`).
   - Workspace selection: single-workspace Phase-1 simplification
     (see **AgentProfile keying** above).
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

## Decision 2-B — Canonicalise the message-history axis (sac vs orochi)

Added 2026-06-01 after a follow-up audit (operator msg #81): the
identity-store collapse (Decision 2) is incomplete because **sac also
persists every cross-agent message**, on top of orochi's hub-side
storage. Same conversation, two systems of record, no sync. This
amendment fixes the message-history axis the same way Decision 2 fixed
the identity axis.

### Current state — sac stores conversations in `state.db` (4 tables)

All paths below are in scitex-agent-container (read-only for this
agent; sac-side cleanup routed to proj-scitex-agent-container via the
appendix table).

| sac store | File / table | Writer | Role | Retention |
|---|---|---|---|---|
| `channel_events` | `~/.scitex/agent-container/runtime/state.db` (schema `_state/state_db.py:216-229`) | `_listen/_node_channel.py:271` `persist_event` on every `POST /agents/<name>/message:send`; also `a2a/_server.py:465` for the standalone a2a path | Full message envelope (`target`, `source`, `kind`, `content`, `meta_json`, `ts`, `delivered_at`). Durability buffer for SSE replay on `inbox/stream` reconnect (durability comment at `_listen/_node_channel.py:259-271`). | Forever (no GC pass; `state_db_gc.py` only collects dead `instances`). |
| `turns` | same `state.db` (schema `_state/state_db.py:167-180`) | `_state/state_db_diary.py:44` `record_turn` via `_runners/_session_state.py:302` (4 rows per turn: `queued`→`delivered`→`read`→`responded`; 5th on `error`) | Receiver-side per-turn state-machine diary; `prompt_text` + `response_text` clipped at 500 chars. | Forever. |
| `dispatches` | same `state.db` (schema `_state/dispatch_ledger.py:60-75`) | `_state/dispatch_ledger.py:113` `record_dispatch` via `_network/peer.py:130 record_dispatch_safe` (BEFORE the HTTP POST) | Sender-side outbound ledger; `from_agent`, `to_agent`, `text_summary` (500-char clip), `conversation_id`, `status` (`sent`/`delivered`/`timeout`/`failed`). | Forever. |
| `session.jsonl` | `~/.scitex/agent-container/runtime/<agent>/session.jsonl` | `_runners/_session_state.py:489-494` `append_session_message` | Per-agent Claude-SDK-native transcript (assistant blocks, user echoes, ResultMessage, errors). Append-only JSONL. | Forever. Read by `_listen/_tail.py:46-127` SSE + `_state/recall.py` (`sac agent recall`). |

In-memory only (NOT durable): `a2a/_inbox_bus.Broker` (per-process
asyncio queues, cap 64, oldest dropped on full — docstring
`a2a/_inbox_bus.py:22-24` is explicit). Every `broker.publish(...)` is
preceded by a `persist_event(...)` on disk, so durability comes from
`channel_events`, not the Broker.

### Overlap with orochi `Message`

`channel_events` is **a near-mirror of orochi's `Message` model**
(`apps/hub/models/_messaging.py`): both store every cross-agent
message body durably, both are keyed by (target/channel, monotonic
id), both carry timestamps + envelopes. When a sac fleet is
registered to orochi, **every peer turn is stored twice**: once on
the sac host (`channel_events` row at `_listen/_node_channel.py:271`,
before publish) and once on the orochi hub (the `Message` row written
when the WS push lands).

`turns` (receiver) + `dispatches` (sender) split each conversation
across **two state.db files on two hosts**. Today, reconstructing
"agent A said X to agent B at T" requires SSHing to both hosts and
joining `dispatches.from_host:state.db` with `turns.to_host:state.db`.
Orochi's `Message` is the only single-host, full-fleet view.

`ChannelMembership` (orochi) has no sac analogue; sac computes group
membership synchronously per-send from `lineage` + `comms_grants`
(`_state/state_db.py:263-277`).

A separate smell: `dispatches` is **not** in `KNOWN_TABLES` (the
`sac db query` allow-list at `_state/state_db.py:330-345`), so it's
invisible to operators via the CLI. The outbound ledger exists but
the user surface to inspect it is closed.

### Proposal — sac is canonical; orochi `Message` is demoted to ephemeral cache

**Revised 2026-06-01 after operator msg #82** ("シングルソースオブトゥルース
ということで、SA Cが持っているものを使う。もしSA C側に拡張するためのポートが
ないならそれを作ってもらうように依頼するっていうのもそうですし、まぁきれいに
大蛇と分けてくれればと思います。"):

The earlier draft of this section made orochi `Message` canonical for
the wrong reason ("it's convenient — has Django joins, a UI, a
ChannelMembership shape"). That violates the north star. The
operator's correction restores SoC consistency with Decision 2 (sac
filesystem inventory = canonical for identity): **sac is canonical for
data; orochi is canonical only for its OWN concept of channels +
membership.** Conversation bodies belong to sac. orochi must read
sac, not duplicate sac.

| Store | After this decision |
|---|---|
| **sac `channel_events`** | **Canonical** source of truth for "agent A said X to agent B at T". Already exists on every sac host. orochi reads from it via new sac extension ports (see below). |
| sac `turns` + `dispatches` | Local diagnostic projections (unchanged shape; cross-host SSH for forensics is fine). Sac-side ticket: add `"dispatches"` to `KNOWN_TABLES`. Retention policy is a sac concern, not orochi's. |
| sac `session.jsonl` | Unchanged. Claude-SDK-native per-agent transcript. |
| **orochi `Message`** | **Demote to ephemeral render cache** (or eliminate). orochi stops persisting message bodies in its own DB. The WS push from sac stays as an ephemeral signal for live-render; history queries from the dashboard route through new sac extension ports. |
| **orochi `ChannelMembership`** | **Canonical (unchanged).** Channels are an orochi concept (a comms-layer routing/grouping artifact); sac has no native equivalent. orochi keeps owning channel definitions + memberships, plus their ACLs. |

### Sac-side extension ports orochi will need (request for proj-scitex-agent-container)

Without these, orochi cannot replace its own `Message` reads with sac
reads. Routing these to the sac project via the appendix:

1. **`GET /v1/fleet/messages`** — fleet-wide aggregation across hosts.
   Query: `?agents=a,b,c&since_ts=T&limit=N&kind=message`. Returns the
   `channel_events` rows for those agents from every host in the
   fleet, merged by `ts`, with the full envelope. Used by orochi's
   dashboard to render channel history.
2. **`GET /v1/agent/<name>/messages?since_id=N&limit=N`** — single-host
   pull cursor. Returns `channel_events` for one agent past the last
   id orochi has seen. Used by the orochi-side ephemeral cache to
   replay missed messages on WS reconnect (replaces the orochi-DB
   write).
3. **`GET /v1/fleet/messages/search?q=...&channel=...&since_ts=...`** —
   server-side search over `channel_events.content` + `meta_json`.
   Used by the dashboard search box. Without this, orochi would need
   to either pull everything (linear) or keep its own search index
   (back to the duplicate-storage problem).
4. **`HEAD /v1/fleet/messages?since_ts=T`** — cheap "has anything
   changed since T" probe for the dashboard's polling fallback when WS
   is unavailable.

These four ports together give orochi everything it needs to be a
true projection of sac's storage. Until they exist, orochi keeps its
`Message` writes as an interim measure; the migration sequencing is in
the Phases table.

### What orochi keeps doing

- WS push from sac arrives -> emit to subscribed dashboards/clients
  immediately (live render). DO NOT persist on orochi.
- ChannelMembership and channel ACLs: orochi-only.
- Aggregation across hosts on behalf of the dashboard: route to
  `GET /v1/fleet/messages` (above).
- Search: route to `GET /v1/fleet/messages/search` (above).

### What orochi stops doing

- `apps/hub/models/_messaging.py:Message` writes on every WS-push
  arrival. The model becomes either (a) a thin in-memory cache, or
  (b) deleted entirely. Choice depends on dashboard latency budget;
  default lean is (b).
- Owning conversation retention. sac sets retention on
  `channel_events`. orochi stops having a retention policy because it
  no longer stores the data.

### Out of scope (this decision, this ADR)

- Cross-host replication of `dispatches`/`turns` — operator can still
  `ssh + sac db query` per host for forensics. Aggregation is only
  promised for `channel_events`.
- Migrating sac `session.jsonl` into orochi — Claude SDK owns that
  file format and orochi has no equivalent.
- Internal sac retention policy for `channel_events` — that is a sac
  concern, not orochi's. We do NOT depend on a specific TTL from sac;
  orochi tolerates whatever sac configures (queries become 404 / empty
  past the TTL boundary). The orochi push-ack watermark idea in the
  earlier draft is dropped: orochi has no authority to gate sac's GC.

### Phases (added to the table below)

- Phase 2B-prereq (sac side, routed to proj-scitex-agent-container):
  implement the 4 extension ports listed above. Without these,
  Phase 2B-orochi cannot proceed.
- Phase 2B-orochi: stop persisting `Message` rows; route history /
  search queries through the new sac ports; make `Message` an in-memory
  cache (or remove). Migration includes orochi sqlite cleanup + Django
  model deprecation.

### Sac-side tickets (handed off via appendix)

Three of these (KNOWN_TABLES, gc sweep, docstring) are retained from
the earlier draft for sac's own hygiene. Four new ones are the
extension ports orochi needs to actually replace its own `Message`
storage.

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
| `scitex-agent-container/src/scitex_agent_container/_state/state_db.py:330` | `dispatches` table is not in `KNOWN_TABLES`. Operators cannot query the sender-side outbound ledger via `sac db query --table=dispatches`. | Add `"dispatches"` to the allow-list. (Decision 2-B hygiene; not blocking.) |
| `scitex-agent-container/src/scitex_agent_container/_state/state_db_gc.py` | No retention sweep for `channel_events` / `turns` / `dispatches`; unbounded growth in long-running fleets. | Decision: sac sets its own retention. orochi tolerates whatever sac configures (no orochi-side gating). The sweep is a sac-internal concern; flag for sac-side scoping, no specific number prescribed here. |
| `scitex-agent-container/src/scitex_agent_container/_state/state_db_channel.py:1-34` | Docstring describes `channel_events` as durable conversation log; under Decision 2-B it is **the canonical store** for cross-agent message bodies. | Promote the canonical role into the docstring's first paragraph; orochi reads from here via the new extension ports. |
| **New: `GET /v1/fleet/messages`** | Sac has no fleet-wide aggregation port over `channel_events`; orochi cannot replace its own `Message` reads without this. | **Request to proj-scitex-agent-container**: implement aggregation port (`?agents=...&since_ts=...&limit=...&kind=...`). Returns merged `channel_events` rows from every host. Decision 2-B prereq. |
| **New: `GET /v1/agent/<name>/messages`** | No single-host pull cursor on sac side; orochi has no way to replay missed messages on WS reconnect without persisting them itself. | **Request to proj-scitex-agent-container**: implement single-host pull (`?since_id=N&limit=N`). Decision 2-B prereq. |
| **New: `GET /v1/fleet/messages/search`** | No server-side search over `channel_events.content` / `meta_json`; dashboard search box would require orochi to index everything (back to the duplicate-storage problem). | **Request to proj-scitex-agent-container**: implement search port (`?q=...&channel=...&since_ts=...`). Decision 2-B prereq. |
| **New: `HEAD /v1/fleet/messages?since_ts=T`** | No cheap "anything changed since T" probe for orochi's dashboard polling fallback when WS is unavailable. | **Request to proj-scitex-agent-container**: implement probe port. Decision 2-B nice-to-have (not blocking for first migration). |

---

## Phases / sequencing

These are independent unless noted. **None of them is authorised by
this ADR** — each requires its own PR with operator sign-off.

| Phase | Decision | Risk | Effort |
|---|---|---|---|
| 1 | Decision 2 step 1 — sac inventory reconciler daemon | Low (additive) | S |
| 2 | Decision 1 — remove `spec.orochi.channels` | Low–Med (touches yamls; deletes a public-looking field) | S |
| 2B-prereq | Decision 2-B — sac implements `GET /v1/fleet/messages`, `GET /v1/agent/<n>/messages`, `GET /v1/fleet/messages/search`, `HEAD /v1/fleet/messages` (routed to proj-scitex-agent-container) | Med (sac side; orochi blocked until done) | M |
| 2B-orochi | Decision 2-B — stop persisting orochi `Message`; route dashboard history/search through new sac ports; deprecate the model | High (touches Django model + UI data flow + cross-repo wire) | L |
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
