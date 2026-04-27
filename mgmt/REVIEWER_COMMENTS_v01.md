# Reviewer Comments -- scitex-orochi Code Review

**Reviewer:** Code Review Agent
**Date:** 2026-04-07
**Scope:** Full source review of `src/scitex_orochi/`, `tests/`, project configuration
**Codebase:** ~6,183 lines of Python across 39 source files + 4 test files

---

## Executive Summary

scitex-orochi is a WebSocket-based agent communication hub with a REST/dashboard layer, Telegram bridge, Gitea integration, workspace isolation, and push notifications. The architecture is sound in concept -- a central message broker with channel routing, @mention delivery, and workspace isolation. However, this review identifies **two critical security vulnerabilities** (auth bypass, token leakage), significant dead/legacy code, and structural issues that need attention.

---

## CRITICAL Issues

### C1. Auth bypass: `verify_token()` called without `await` in multiple endpoints

**Files:** `_web_gitea.py:37`, `_web_push.py:40`, `_web_push.py:79`

`verify_token` is defined as `async def` in `_auth.py:26`, but three HTTP handlers call it **without `await`**:

```python
# _web_gitea.py:37
if not verify_token(token):   # BUG: returns coroutine object, always truthy
```

A coroutine object is always truthy in Python. This means:
- `POST /api/gitea/issues/{owner}/{repo}` -- **anyone can create Gitea issues without authentication**
- `POST /api/push/subscribe` -- **anyone can register push subscriptions**
- `POST /api/push/unsubscribe` -- **anyone can remove push subscriptions**

The auth check is completely inert. This is a live security vulnerability.

**Severity:** CRITICAL
**Fix:** Add `await` to all three call sites.

### C2. Admin token leaked via unauthenticated endpoint

**File:** `_web.py:165-181`

```python
async def handle_config(request: web.Request) -> web.Response:
    """GET /api/config -- dashboard configuration."""
    ...
    return web.json_response({
        "version": ver,
        "ws_upstream": DASHBOARD_WS_UPSTREAM or "",
        "dashboard_token": ADMIN_TOKEN,  # <-- LEAKED
    })
```

`GET /api/config` requires **no authentication** and returns the `ADMIN_TOKEN` in plaintext. Anyone who can reach the HTTP port obtains full admin access. Combined with C1, this makes the entire auth system moot if the dashboard port is exposed.

**Severity:** CRITICAL
**Fix:** Either require auth for this endpoint, or stop including the token in the response. The dashboard should receive its token through a different channel (e.g., injected at deploy time).

---

## IMPORTANT Issues

### I1. Unauthenticated read endpoints expose internal data

**File:** `_web_gitea.py`

These endpoints require **no token at all**:
- `GET /api/gitea/issues/{owner}/{repo}` -- lists Gitea issues (proxied with the server's Gitea token)
- `GET /api/gitea/repos` -- lists Gitea repos
- `GET /api/github/issues` -- proxies GitHub API

Also unauthenticated:
- `GET /api/agents` -- lists all connected agents, their machines, roles, IPs
- `GET /api/resources` -- lists CPU/memory metrics of all agents
- `GET /api/channels`, `GET /api/messages`, `GET /api/history/*`
- `GET /api/stats`, `GET /api/workspaces`

Any of these can be probed by an unauthenticated user.

**Severity:** Important

### I2. Hardcoded GitHub repo in production code

**File:** `_web_gitea.py:72`

```python
github_url = (
    "https://api.github.com/repos/ywatanabe1989/todo/issues?state=open&per_page=30"
)
```

This is a developer's personal TODO repo hardcoded into the proxy. It should be configurable or removed.

**Severity:** Important

### I3. Dead code: `health_cmd.py` and `listen` command never registered

**File:** `_cli/commands/health_cmd.py` (68 lines) -- Defines `health_cmd` but it is **never imported or registered** in `_cli/_main.py`. It is completely dead code.

**File:** `_cli/commands/messaging_cmd.py` -- Defines a `listen` command (lines 64-105) but it is **not imported or registered** in `_cli/_main.py` (only `send`, `login`, `join` are imported).

**Severity:** Important (dead code misleads maintainers, `listen` is likely a missing feature)

### I4. Version mismatch between `__init__.py` and `pyproject.toml`

- `src/scitex_orochi/__init__.py:3` declares `__version__ = "0.2.0"`
- `pyproject.toml:7` declares `version = "0.4.0"`

The runtime version and the build version are out of sync. Anyone calling `scitex_orochi.__version__` gets stale information.

**Severity:** Important
**Fix:** Use `importlib.metadata.version("scitex-orochi")` as the single source of truth, or keep them in sync via hatchling's version hook.

### I5. Module reload pattern for configuration is fragile

**Files:** `_main.py:46-53`, `tests/test_server.py:27-33`, `tests/test_telegram_bridge.py:249-253`

The codebase uses `importlib.reload()` on `_config` and `_auth` modules to pick up environment variable changes. This is a pattern that:
- Breaks if any other module has already imported constants by value (e.g., `from _config import ADMIN_TOKEN`)
- Is used in production code (`_main.py`), not just tests
- Creates hidden coupling between import order and runtime behavior

**Severity:** Important
**Fix:** Use a function-based config accessor (e.g., `get_admin_token()`) rather than module-level constants, or use a config singleton that can be updated.

### I6. Django residue: `hub/`, `orochi/`, `db.sqlite3`

The `hub/` directory contains Django management commands, migrations, providers, and template tags -- all as `.pyc` files only (no `.py` sources). The `orochi/` directory has Django settings `.pyc` files. There is a `db.sqlite3` at project root (320KB).

These appear to be remnants of an earlier Django-based architecture. The current codebase is pure aiohttp/websockets. Having compiled-only Django artifacts in the repo is confusing and potentially ships stale code.

**Severity:** Important
**Fix:** Remove `hub/`, `orochi/`, `db.sqlite3` if Django is no longer used. If they serve a purpose, the `.py` source files should be present rather than only `.pyc`.

### I7. `asyncio.ensure_future` used for fire-and-forget (deprecated pattern)

**File:** `_server.py:423`

```python
asyncio.ensure_future(self._broadcast_to_observers(...))
```

`asyncio.ensure_future` does not handle exceptions from the resulting task -- if `_broadcast_to_observers` throws, the exception is silently swallowed (or triggers a "Task exception was never retrieved" warning). Use `asyncio.create_task` and store/log the result.

**Severity:** Important

### I8. `OrochiServer.start()` duplicates WebSocket server setup with `_main.py`

**File:** `_server.py:78-89` defines `async def start()` which calls `websockets.serve(...)`.
**File:** `_main.py:81-87` also calls `websockets.serve(...)` on the same handler.

The `start()` method runs `await asyncio.Future()` (blocks forever), while `_main.py` does its own orchestration. The `start()` method is effectively unused dead code since the real entry point is `_main.main()`.

**Severity:** Important

---

## NICE-TO-HAVE Issues

### N1. No rate limiting on any endpoint

All REST and WebSocket endpoints accept unlimited requests. A misbehaving agent or external actor could flood the server with messages, uploads, or subscription registrations.

### N2. Push notification hook re-reads VAPID keys from disk on every message

**File:** `_push_hook.py:33`

```python
keys = load_vapid_keys(get_vapid_keys_path())
```

This reads and parses a JSON file from disk on every single channel message. VAPID keys are static -- they should be loaded once at startup.

### N3. `_web.py:44` passes `verify_token` without workspace_store

```python
if not await verify_token(token):
```

In `handle_ws`, `verify_token` is called with only the token (no `workspace_store` argument). This means workspace tokens cannot authenticate dashboard WebSocket connections -- only the admin token works. This may be intentional but limits workspace-scoped dashboard access.

### N4. `send_push_to_all` removes subscriptions on ANY failure, not just 410/404

**File:** `_push.py:231-232`

The docstring says "Removes subscriptions that return 404/410 (unsubscribed)" but the code removes on any failure (`ok == False`), including network timeouts. This could incorrectly purge valid subscriptions during transient network issues.

### N5. No connection pooling for Telegram API or Gitea client

- `TelegramBridge` creates one `aiohttp.ClientSession` but `GiteaClient` lazily creates one without connection limits.
- Each MCP tool call in `mcp_server.py` creates a full WebSocket connection, registers, executes, and disconnects. For frequent MCP usage, this is wasteful.

### N6. `_store.py` pruning strategy has a subtle issue

**File:** `_store.py:82-87`

The pruning uses `ORDER BY ts DESC` to keep the most recent 5000 messages, but `ts` is a TEXT ISO timestamp. SQLite text comparison works for ISO 8601, but if any timestamp has inconsistent formatting (e.g., different timezone representations), the ordering could be wrong.

### N7. Token passed in query string (URL)

Throughout the codebase, authentication tokens are passed as `?token=xxx` in URLs. This means tokens appear in:
- Server access logs
- Browser history
- Proxy logs
- Referrer headers

Standard practice is to use `Authorization` headers instead.

### N8. `_config.py` ADMIN_TOKEN fallback chain is confusing

```python
ADMIN_TOKEN = _env("SCITEX_OROCHI_ADMIN_TOKEN", "")
if not ADMIN_TOKEN:
    ADMIN_TOKEN = _env("SCITEX_OROCHI_TOKEN", "")
OROCHI_TOKEN = ADMIN_TOKEN  # alias
```

Then `_main.py` generates a token, writes it to both env vars, and reloads the module. The aliasing and fallback make it unclear which env var is canonical.

### N9. `doctor_cmd.py` double-prints checks

**File:** `doctor_cmd.py:71-77`

```python
results.append(
    _check("Server", True, f"{host}:{port}")   # _check prints AND returns
    if not as_json
    else {"check": "Server", "ok": True, "detail": f"{host}:{port}"}
)
if not as_json:
    _check("Server", True, f"{host}:{port}")   # printed AGAIN
```

The server check is printed twice in non-JSON mode because `_check()` has a side effect (printing) and is also called explicitly afterward.

### N10. `node_modules/` in project root

The project root contains `node_modules/`, suggesting a Node.js dependency (possibly for the dashboard). This should be in `.gitignore` and not shipped with the Python package.

---

## Test Coverage Assessment

**What is tested (4 test files, ~300 lines):**
- `test_server.py`: Registration, messaging, @mention routing, presence, heartbeat, status update, auth rejection, extended fields -- Good coverage of core server
- `test_telegram_bridge.py`: Relay filtering, echo prevention, update processing, photo/voice attachments, config validation -- Good coverage
- `test_web.py`: REST endpoints (agents, channels, stats, history), dashboard WebSocket observer -- Reasonable coverage
- `test_workspace_auth.py`: Token auth, workspace isolation, cross-workspace delivery blocking -- Good coverage

**What is NOT tested:**
- `_config_loader.py` (YAML config loading, template rendering, agent name parsing)
- `_push.py` / `_push_hook.py` (push notifications, VAPID key generation)
- `_media.py` (file uploads)
- `_gitea.py` / `_gitea_handler.py` (Gitea API client, dispatch)
- `_web_gitea.py`, `_web_push.py`, `_web_workspaces.py` (REST route handlers)
- `_resources.py` (system metrics collection)
- `mcp_server.py` (MCP tool interface)
- All CLI commands (`launch_cmd.py`, `doctor_cmd.py`, `messaging_cmd.py`, etc.)
- `_client.py` (OrochiClient -- only tested indirectly via server tests)

**Critical gap:** The auth bypass bug (C1) would have been caught by a test that verifies push/gitea endpoints reject unauthenticated requests.

---

## Architectural Observations

1. **The project has outgrown its single-process architecture.** The WebSocket server, HTTP server, Telegram bridge, and push notification system all run in one process. There is no horizontal scaling path.

2. **SQLite is used for everything** (messages, workspaces, push subscriptions) with a single DB file. The workspace store shares the message store's DB connection (`server.store._db`). This tight coupling means workspace operations can block message persistence.

3. **The legacy config system (`orochi-config.yaml` + screen + SSH) coexists with the new agent-container system.** The launch_cmd.py has ~300 lines of legacy fallback code. This duplication should be resolved.

4. **Module-level state** (config values, logging setup) makes testing require `importlib.reload()` hacks. This is a design smell that compounds as the codebase grows.

---

## Summary of Findings

| Severity | Count | Key Items |
|----------|-------|-----------|
| CRITICAL | 2 | Auth bypass (missing `await`), Admin token leaked via `/api/config` |
| IMPORTANT | 8 | Unauthenticated endpoints, hardcoded repo, dead code, version mismatch, Django residue, fragile config reload, duplicate server setup |
| NICE-TO-HAVE | 10 | No rate limiting, disk I/O per message, query-string tokens, double-print bug, etc. |

---

## Prioritized Recommendations

1. **Immediately fix C1 and C2** -- these are exploitable security vulnerabilities
2. **Add auth to all read endpoints** or document the explicit decision to leave them open
3. **Remove dead code** (`health_cmd.py`, unreachable `listen`, `OrochiServer.start()`, Django artifacts)
4. **Sync versions** between `__init__.py` and `pyproject.toml`
5. **Replace `importlib.reload()` pattern** with function-based config access
6. **Add tests for auth enforcement** on web endpoints
7. **Cache VAPID keys** in memory rather than re-reading from disk per message
8. **Remove hardcoded GitHub repo** or make it configurable
9. **Plan migration away from legacy launch system** to agent-container exclusively
