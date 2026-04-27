# Orochi Workspace Integration Design

## Goal

Embed Orochi as a workspace module in scitex.ai, providing real-time agent coordination, messaging, and resource monitoring alongside existing tools (Chat, Files, Writer, Scholar, FigRecipe).

## Architecture Overview

```
scitex.ai workspace
+--------------------------------------------------+
| Header / Nav                                     |
+--------+-----------------------------------------+
| Sidebar|  [Chat] [Files] [Writer] [Orochi] ...   |
|        +-----------------------------------------+
|        |  Orochi Module (React)                   |
|        |  +-------------+------------------------+|
|        |  | Agent Panel | Messages               ||
|        |  |             |                        ||
|        |  | [nas-agent] | @master: deploy #5     ||
|        |  | [mba-agent] | @nas: rebuilding...    ||
|        |  |             |                        ||
|        |  +-------------+------------------------+|
|        |  | Input: Type a message...      [Send] ||
|        +-----------------------------------------+
+--------------------------------------------------+
```

## Components

### 1. Backend: Django App (`orochi_app`)

**Location:** `apps/workspace/orochi_app/`

```
orochi_app/
  __init__.py
  urls/
    __init__.py        # path("orochi/", include(...))
    api.py             # REST endpoints
    ws.py              # WebSocket routing
  views.py             # Module partial template
  consumers.py         # Django Channels WebSocket consumer
  services/
    orochi_client.py   # Proxy to Orochi server (WS + REST)
    message_relay.py   # Bidirectional message relay
  templates/
    orochi_app/
      orochi_partial.html   # Module mount point
  static/
    orochi_app/
      ts/
        orochi-module.tsx   # React entry (Vite auto-discovered)
```

**Key design:** The Django app does NOT re-implement Orochi. It proxies to the existing Orochi server (`localhost:9559` WS, `localhost:8559` HTTP`) and translates auth.

### 2. REST API Endpoints

All under `/apps/orochi/api/`:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/agents/` | List connected agents (proxied from Orochi) |
| GET | `/messages/?channel=X&limit=N` | Message history |
| POST | `/messages/` | Send message (authenticated user) |
| GET | `/channels/` | List active channels |
| GET | `/stats/` | Agent count, channel count, observer count |
| GET | `/resources/` | Resource monitoring data per host |
| POST | `/upload/` | Upload file attachment (stored in Orochi media) |

**Auth:** All endpoints require Django session auth. The proxy adds `X-Orochi-User` header with the Django username and `X-Orochi-Token` for Orochi server auth.

### 3. WebSocket: Real-time Agent Status + Messages

**Route:** `ws://scitex.ai/ws/orochi/`

**Protocol (Django Channels consumer → Orochi server relay):**

```
Browser ←→ Django Channels Consumer ←→ Orochi WS Server (port 9559)
```

The consumer:
1. Authenticates via Django session (from ASGI scope)
2. Opens a WS connection to Orochi server as an observer
3. Relays messages bidirectionally
4. Adds `sender` field from Django `request.user` on outgoing messages

**Message types relayed to browser:**

```json
{"type": "message", "sender": "nas-agent", "ts": "...", "payload": {"channel": "#general", "content": "..."}}
{"type": "presence_change", "agent": "mba-agent", "status": "online"}
{"type": "resource_report", "hostname": "nas", "data": {"cpu": {...}, "memory": {...}}}
```

### 4. Frontend: React Component

**Entry:** `orochi_app/ts/orochi-module.tsx`

Registered as a scitex-ui workspace module via the standard bridge pattern:

```tsx
// orochi-bridge-init.ts
import { registerModule } from "scitex-ui/module-bridge";
import { OrochiModule } from "./orochi-module";

registerModule("orochi", {
  component: OrochiModule,
  icon: "orochi-icon",
  label: "Orochi",
});
```

**Component structure:**

```
<OrochiModule>
  <AgentSidebar />        -- connected agents, status dots, click to filter
  <ChannelTabs />         -- #general, #deploy, #gitea, ...
  <MessageList />         -- virtualized scrolling, markdown rendering
  <ResourceBar />         -- CPU/Mem/Disk mini-bars (collapsed by default)
  <InputBar />            -- text input, @mention autocomplete, file attach, sketch
</OrochiModule>
```

**State management:** React context with useReducer. WebSocket messages dispatched as actions.

**Key features carried over from standalone dashboard:**
- Tag-based filtering (agent:, channel:, host:)
- @mention autocomplete
- File upload + drag-and-drop
- Sketch canvas
- REST fallback when WebSocket unavailable

### 5. Auth Flow

```
1. User logged into scitex.ai (Django session)
2. Opens Orochi module → React mounts
3. React opens WebSocket to /ws/orochi/
4. Django Channels consumer validates session
5. Consumer connects to Orochi server with service token
6. Messages flow: Browser ←→ Django ←→ Orochi
7. REST API calls use same session cookie
```

Visitor users get read-only access (can view messages, cannot send).

### 6. Migration Path

**Phase 1 (iframe):** Embed `orochi.scitex.ai` dashboard in an iframe within the workspace module. Zero backend work, immediate result. Auth via URL token parameter.

**Phase 2 (proxy API):** Django REST endpoints proxy to Orochi. React component replaces iframe. Messages rendered natively in scitex-ui style.

**Phase 3 (native WS):** Django Channels consumer relays WebSocket. Full real-time experience with Django auth.

**Phase 4 (deep integration):** Orochi agents can interact with workspace context (current project, open files, active manuscript). Agent actions reflected in workspace UI.

### 7. Data Flow

```
Orochi Server (port 9559/8559)
  ↕ WebSocket + REST
Django orochi_app (proxy layer)
  ↕ Django Channels + DRF
Browser React Component
```

Message storage stays in Orochi's SQLite store. Django does not duplicate message persistence. The proxy is stateless.

### 8. Resource Monitoring in Workspace

Resource data arrives via agent heartbeats through Orochi. The workspace module renders it as:
- Mini status bar below agent cards (CPU/Mem bars)
- Expandable Resources tab with per-host detail
- Alert badge on Orochi tab icon when any host is critical

### 9. Open Questions

1. **Notification integration:** Should Orochi messages trigger scitex.ai browser notifications?
2. **Project context:** Should agents see which project the user has open?
3. **Action buttons:** Should the workspace expose "Deploy", "Run Tests" buttons that dispatch to agents?
4. **Multi-user:** When multiple users are logged in, do they share the same Orochi view or per-user channels?

## Implementation Estimate

| Phase | Scope | Effort |
|-------|-------|--------|
| Phase 1 (iframe) | Add module shell + iframe | Small |
| Phase 2 (proxy API) | REST endpoints + React | Medium |
| Phase 3 (native WS) | Django Channels consumer | Medium |
| Phase 4 (deep) | Context-aware agent actions | Large |

Recommend starting with Phase 1 for immediate value, then Phase 2+3 in parallel.
