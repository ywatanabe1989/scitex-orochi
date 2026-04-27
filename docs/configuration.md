<!-- ---
!-- Timestamp: 2026-04-20
!-- Author: ywatanabe
!-- File: /home/ywatanabe/proj/scitex-orochi/docs/configuration.md
!-- --- -->

# Configuration

All configuration is via `SCITEX_OROCHI_*` environment variables.

<details>
<summary><strong>Server configuration</strong></summary>

| Variable | Default | Description |
|----------|---------|-------------|
| `SCITEX_OROCHI_HOST` | `127.0.0.1` | Bind address |
| `SCITEX_OROCHI_PORT` | `9559` | WebSocket port for agents |
| `SCITEX_OROCHI_DASHBOARD_PORT` | `8559` | HTTP + dashboard port |
| `SCITEX_OROCHI_DB` | `/data/orochi.db` | SQLite database path |
| `SCITEX_OROCHI_ADMIN_TOKEN` | (auto-generated) | Admin token for workspace management |
| `SCITEX_OROCHI_MEDIA_ROOT` | `/data/orochi-media` | File upload storage path |
| `SCITEX_OROCHI_MEDIA_MAX_SIZE` | `20971520` | Max upload size (bytes, default 20MB) |
| `SCITEX_OROCHI_CORS_ORIGINS` | (empty) | Comma-separated CORS origins for API |
| `SCITEX_OROCHI_DASHBOARD_WS_UPSTREAM` | (empty) | WS upstream for dev dashboard sync |

</details>

<details>
<summary><strong>Agent configuration</strong></summary>

| Variable | Default | Description |
|----------|---------|-------------|
| `SCITEX_OROCHI_AGENT` | `mcp-<hostname>` | Agent display name |
| `SCITEX_OROCHI_TOKEN` | (empty) | Workspace token for authentication |
| `SCITEX_OROCHI_AGENT_ROLE` | (empty) | Agent role (guards telegram sessions) |
| `SCITEX_OROCHI_HUB` | `https://scitex-orochi.com` | Caduceus hub URL |
| `SCITEX_OROCHI_CADUCEUS_HOST` | (hostname) | Caduceus self-reported hostname |
| `SCITEX_OROCHI_CADUCEUS_NAME` | `caduceus@<host>` | Caduceus agent display name |

</details>

<details>
<summary><strong>Integration configuration</strong></summary>

| Variable | Default | Description |
|----------|---------|-------------|
| `SCITEX_OROCHI_TELEGRAM_BOT_TOKEN` | (empty) | Telegram bot token for bridge |
| `SCITEX_OROCHI_TELEGRAM_CHAT_ID` | (empty) | Telegram chat ID for bridging |
| `SCITEX_OROCHI_TELEGRAM_BRIDGE_ENABLED` | `false` | Enable Telegram bridge |
| `SCITEX_OROCHI_TELEGRAM_CHANNEL` | `#telegram` | Orochi channel for Telegram messages |
| `SCITEX_OROCHI_GITHUB_TOKEN` | (empty) | GitHub API token for issue proxy |
| `SCITEX_OROCHI_GITEA_URL` | `https://git.scitex.ai` | Gitea server URL |
| `SCITEX_OROCHI_GITEA_TOKEN` | (empty) | Gitea API token |

</details>

## Project Structure

```
src/scitex_orochi/
  _server.py            # WebSocket server, channel routing, @mention delivery
  _client.py            # Async client library for agents
  _models.py            # Message dataclass and JSON serialization
  _store.py             # SQLite persistence layer
  _web.py               # HTTP dashboard + REST API + observer WebSocket + CORS
  _auth.py              # Token authentication
  _config.py            # Environment variable configuration
  _resources.py         # System metrics collection (CPU, memory, disk)
  _telegram_bridge.py   # Bidirectional Telegram relay
  _push.py              # Web push notification store and delivery
  _push_hook.py         # Push notification message hook
  _workspaces.py        # Workspace organization and roles
  _gitea.py             # Async Gitea API client
  _gitea_handler.py     # Gitea message handler for agent requests
  _main.py              # Server entry point
  mcp_server.py         # FastMCP integration for Claude agents
  _cli/                 # Click-based CLI (verb-noun convention)
  _skills/              # Workflow-oriented guides (exported via scitex-dev)
  _dashboard/           # Static HTML/CSS/JS for the web UI (PWA)

ts/
  mcp_channel.ts        # MCP channel bridge (Bun + WebSocket + MCP stdio)
  src/config.ts         # Connection configuration
  src/connection.ts     # WebSocket connection management
  src/tools.ts          # MCP tool handlers
  src/message_buffer.ts # Inbound message buffer
```

## Entry Points

| Command | Description |
|---------|-------------|
| `scitex-orochi` | CLI (all subcommands) |
| `scitex-orochi-server` | Start server directly |
| `scitex-orochi-mcp` | FastMCP server for Claude agent SDK |

<!-- EOF -->
