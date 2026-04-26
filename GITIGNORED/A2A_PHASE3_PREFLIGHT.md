<!-- ---
!-- Timestamp: 2026-04-26
!-- Author: ywatanabe (spike: spike/a2a-phase3-preflight)
!-- File: GITIGNORED/A2A_PHASE3_PREFLIGHT.md
!-- --- -->

# A2A Phase 3 — Pre-flight findings

Worktree: `/home/ywatanabe/proj/scitex-orochi/.claude/worktrees/agent-af34c763`
Branch: `spike/a2a-phase3-preflight` (off `develop`)
Spike script (kept in `/tmp`, not committed): `/tmp/a2a_phase3_spike.py`

Resolves the four "Open questions / pre-flight" items in
`GITIGNORED/A2A_MIGRATION.md`.

---

## 1. Spike — SDK Starlette routes cohabit with Django ASGI? **YES.**

The a2a-sdk does **not** ship a single Starlette `Application` (no
`a2a.server.apps` package); instead it exposes route-list factories:

- `a2a.server.routes.jsonrpc_routes.create_jsonrpc_routes(handler, rpc_url)`
- `a2a.server.routes.agent_card_routes.create_agent_card_routes(card)`
- `a2a.server.routes.rest_routes.create_rest_routes(...)`

These return `list[starlette.routing.Route]`, which we wrap in a
`Starlette(routes=...)` sub-app. `orochi/asgi.py` already uses
`ProtocolTypeRouter`, so the cleanest wiring is to **replace the bare
`django_asgi_app` under the `"http"` key with a tiny dispatcher** that
forwards `/v1/agents/...` to the Starlette sub-app and everything else
to Django:

```python
# orochi/asgi.py (Phase 3 sketch)
async def http_router(scope, receive, send):
    if scope["path"].startswith("/v1/agents/"):
        return await a2a_starlette_app(scope, receive, send)
    return await django_asgi_app(scope, receive, send)

application = ProtocolTypeRouter({
    "http": http_router,
    "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
})
```

Spike result (`/tmp/spike_out.txt`):
```
SDK card status: 200
SDK card body[:200]: b'{"name":"proj-hello-world","description":"spike","version":"0.0.1"}'
```

Notes from the spike:
- `AgentCard` is a **protobuf** message (not pydantic). Use
  attribute assignment, not constructor kwargs (`card.name = ...`).
- `DefaultRequestHandler` requires `agent_card=` (positional). The
  class is internally `DefaultRequestHandlerV2`.
- For per-agent routing (cardinality), production should construct a
  Starlette `Mount("/v1/agents/{name}", app=...)` once at startup,
  with a custom `ServerCallContextBuilder` that pulls `name` from the
  path and resolves the registry entry inside `OrochiAgentExecutor`.
  A single shared executor + registry lookup is cleaner than building
  N Starlette apps.

Verdict: **no blocker**. Wiring is ~10 lines in `orochi/asgi.py`
plus a new `hub/a2a/` module.

---

## 2. Inventory — consumers of `/api/a2a/dispatch/<slug>/<agent>/`

**In scitex-orochi:**
- `hub/urls.py:120` — route definition
- `hub/urls_bare.py:181` — route definition (bare/MCP urlconf)
- `hub/views/api/_a2a_dispatch.py` — implementation
- `docs/a2a-protocol.md:34` — narrative reference
- `docs/a2a-protocol.md:122` — `SCITEX_OROCHI_HUB_URL` env var description

**In scitex-agent-container:**
- `src/scitex_agent_container/_skills/scitex-agent-container/07_a2a-protocol.md:105`
  — only a documentation reference describing the dispatch chain.
  No code caller.

**In scitex-cloud:** no source-code references found
(`/home/ywatanabe/proj/scitex-cloud/{src,scitex,apps,lib}/...`).
The 452 KB grep hits in scitex-cloud are entirely from
`deployment/singularity/current-sandbox/usr/local/lib/.../litellm/`
vendored deps that match `/v1/agents` — **unrelated** to orochi's
dispatch URL.

**In `~/.scitex/orochi/shared/`:** no references.

**Phase 4 cutover impact:** ~zero external-source consumers. The
URL is reached today only via:
1. NAS Django reverse-proxying `https://a2a.scitex.ai/api/a2a/dispatch/...`
2. Cloudflare → orochi public route
3. Documentation that needs a one-line update

Practical implication: the deprecation window can be **short** (one
minor release with a `Deprecation:` header should suffice).

---

## 3. Task store — Redis is feasible **but the SDK does not ship a Redis backend.**

Redis status in orochi today:
- `pyproject.toml:28` — `channels-redis>=4.2` is a runtime dep.
- `deployment/docker/docker-compose.stable.yml:54-60` — Redis 7-alpine
  service, ephemeral (`--save "" --appendonly no`), used only for
  Channels group routing. Confirmed: `REDIS_URL=redis://redis:6379/0`.

a2a-sdk task-store backends shipped (in
`/home/ywatanabe/.env-3.11/lib/python3.11/site-packages/a2a/server/tasks/`):
- `inmemory_task_store.py` — `InMemoryTaskStore`
- `database_task_store.py` — `DatabaseTaskStore` (SQLAlchemy async)
- `copying_task_store.py` — wrapper, not a backend

**Gap**: there is **no `redis_task_store.py`** in the SDK.

Recommendation revision: the navigator's "Redis (already a dep)"
recommendation is **partially incorrect** — Redis is in the stack but
the SDK can't natively use it. Two options for Phase 3:

1. **Start with `InMemoryTaskStore`** (matches today's `_PENDING`
   semantics in `_a2a_dispatch.py`; single daphne process is fine
   for current scale). Zero new infra. Lose tasks across restarts.
2. **Use `DatabaseTaskStore`** pointed at orochi's existing Postgres
   (sqlite in dev). Persists across restarts, no new dep, matches
   the doc's eventual "scitex-cloud postgres" path. The SDK already
   ships an Alembic migration tree at
   `/home/ywatanabe/.env-3.11/lib/python3.11/site-packages/a2a/migrations/`.

Recommend **option 2** for Phase 3. Skip Redis until horizontal scaling
forces it; at that point write a `RedisTaskStore(TaskStore)` subclass
(the protocol is small — see `task_store.py`).

---

## 4. Auth — workspace-token helpers Phase 3 should wire into SDK middleware

Today's `/api/a2a/dispatch/...` (`hub/views/api/_a2a_dispatch.py:99-110`)
is `@csrf_exempt` + `@require_POST`, no auth.

Existing token primitives:
- **Model**: `hub.models.WorkspaceToken` (defined in
  `hub/models/_identity.py:30`). `wks_*` prefix (see
  `_helpers._generate_workspace_token`).
- **Re-export**: `hub/views/api/_common.py:37,57` re-exports it for the
  whole api package.
- **Canonical lookup pattern** used everywhere in the api package:
  ```python
  WorkspaceToken.objects.select_related("workspace").get(token=token_str)
  ```
  Examples:
  - `hub/views/api/_channels.py:66` — token via `?token=wks_...`
  - `hub/views/api/_export.py:40` — same
  - `hub/views/api/_fleet.py:166` — same
  - `hub/views/api/_auto_dispatch.py:65` — accepts token from query OR
    JSON body (good template for A2A since A2A bodies are JSON-RPC)
  - `hub/views/api/_agents_register.py:43`
  - `hub/views/api/_agents.py:28,123,236,301`
  - `hub/views/api/_agents_lifecycle.py:42,186`
  - `hub/views/api/_misc.py:77`
  - `hub/views/api/_cron.py:99`

**No central middleware/decorator exists** — every endpoint inlines
the same `WorkspaceToken.objects.get(token=...)` lookup. Phase 3
should:

1. Extract a small helper, e.g.
   `hub.views.api._common.resolve_workspace_token(request) -> Workspace | None`,
   that checks (in priority order) `Authorization: Bearer wks_...`
   header, then `?token=`, then JSON body `token`.
2. Wire it into the SDK's `ServerCallContextBuilder` so
   `OrochiAgentExecutor.execute()` can reject unauthenticated calls
   *and* know which workspace the caller belongs to (the URL only
   carries `<agent>` in the canonical scheme — workspace must come
   from the bearer).
3. Keep the compat URL `/api/a2a/dispatch/<slug>/...` permissive
   during the deprecation window (workspace comes from the URL slug).

The SDK exposes auth hooks in `a2a/auth/` — the right integration
point is a custom `ServerCallContextBuilder` (see
`a2a/server/routes/common.py:42`) that returns a
`ServerCallContext` carrying the resolved workspace_id, which
`OrochiAgentExecutor` then passes to `_resolve_workspace_id` /
`_agent_group`.

---

## New blockers / unknowns discovered

- None blocking. Two minor surprises:
  1. `AgentCard` uses **protobuf**, not pydantic — affects how Phase 3
     constructs cards. The existing
     `scitex_agent_container._card.project_card` helper (referenced
     in the navigator) needs to be sanity-checked against this.
  2. SDK has no Redis task store; navigator's Redis recommendation
     should be revised to Postgres (`DatabaseTaskStore`) for Phase 3.

## Summary checklist for Phase 3 start

- [x] Daphne can host both apps (proven)
- [x] Phase 4 cutover blast radius mapped (4 files in orochi, 0 external code)
- [x] Task store: use `DatabaseTaskStore` against orochi's Postgres/SQLite
- [x] Auth: factor `resolve_workspace_token()` helper, plug into
      `ServerCallContextBuilder`
- [ ] (Blocked on sac Phase 1) — borrow sac's `OrochiAgentExecutor`
      shape and `project_card` helper

<!-- EOF -->
