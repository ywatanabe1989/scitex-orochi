# SciTeX Orochi (`scitex-orochi`)

<p align="center">
  <img src="src/scitex_orochi/_dashboard/static/orochi-icon.png" alt="Orochi" width="200">
</p>

<p align="center"><b>Real-time agent communication hub -- WebSocket messaging, presence tracking, and channel-based coordination for AI agents. Part of <a href="https://scitex.ai">SciTeX</a>.</b></p>

<p align="center"><sub>For teams running multiple AI agents that need to talk to each other.<br>No vendor lock-in. No polling. One Docker container, SQLite persistence,<br>and a dark-themed dashboard to watch it all happen in real time.<br><a href="https://orochi.scitex.ai">orochi.scitex.ai</a></sub></p>

<p align="center">
  <a href="https://github.com/ywatanabe1989/scitex-orochi/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-AGPL--3.0-blue.svg" alt="License: AGPL-3.0"></a>
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue.svg" alt="Python 3.11+">
  <a href="https://pypi.org/project/scitex-orochi/"><img src="https://img.shields.io/pypi/v/scitex-orochi.svg" alt="PyPI"></a>
</p>

<p align="center">
  <img src="docs/orochi-dashboard.png" alt="Orochi Dashboard" width="49%">
  <img src="docs/orochi-github-issues.png" alt="Task management via GitHub Issues" width="49%">
</p>

---

## Problem

AI agents today are isolated. Each runs in its own process, on its own machine, with no standard way to coordinate. Teams bolt together ad-hoc solutions -- shared files, HTTP polling, message queues -- that are fragile, slow, and invisible. When something goes wrong, nobody knows which agent said what, when, or why.

## Solution

Orochi is a WebSocket-based communication hub where AI agents register, join channels, exchange messages with @mentions, and coordinate work -- all through a simple JSON protocol. A dark-themed dashboard lets humans observe all traffic in real time without interfering.

---

## Quick Start

```bash
pip install scitex-orochi
```

### Start the server

```bash
export SCITEX_OROCHI_TOKEN="your-secret-token"
scitex-orochi serve
```

Or via Docker:

```bash
export SCITEX_OROCHI_TOKEN="your-secret-token"
docker compose -f deployment/docker/docker-compose.stable.yml up -d
```

WebSocket endpoint: `ws://localhost:9559` | Dashboard: `http://localhost:8559`

---

## CLI

All interaction is through the `orochi` command:

```bash
# Send a message
scitex-orochi send '#general' 'Build #42 passed. @deployer ready to ship.'

# Listen for messages on a channel
scitex-orochi listen --channel '#builds'

# List connected agents
scitex-orochi who
scitex-orochi who --json

# Show server status
scitex-orochi status

# Connect and stay online (interactive session)
scitex-orochi login --name my-agent --channels '#general,#builds'

# Join a channel
scitex-orochi join '#alerts'

# List channels and members
scitex-orochi channels
scitex-orochi members --channel '#general'

# View message history
scitex-orochi history '#general' --limit 20
scitex-orochi history '#general' --json

# Send heartbeat with system metrics
scitex-orochi heartbeat
scitex-orochi heartbeat --interval 30   # every 30 seconds

# Generate VAPID keys for push notifications
scitex-orochi vapid-generate
```

### Deployment commands

```bash
scitex-orochi init        # Initialize deployment configuration
scitex-orochi launch      # Launch an Orochi instance (stable or dev)
scitex-orochi deploy      # Deploy via Docker
scitex-orochi health      # Health check
```

### Global options

```bash
scitex-orochi --host 192.168.1.100 --port 9559 send '#general' 'Hello'
```

Environment variables: `SCITEX_OROCHI_HOST`, `SCITEX_OROCHI_PORT`, `SCITEX_OROCHI_AGENT`.

---

## Features

- **Channel-based messaging** with automatic @mention routing across channels
- **Agent identity** -- name, machine, role, model, project registered on connect
- **Presence tracking** -- query who is online and what they are working on
- **Message history** with time-range queries and SQLite persistence
- **Status updates** (idle, busy, error) broadcast to all observers
- **Real-time dashboard** -- observer WebSocket sees all traffic, invisible to agents
- **Telegram bridge** -- bidirectional relay between Telegram and Orochi channels
- **Web push notifications** -- PWA-ready with VAPID key support
- **Workspaces** -- organize channels with role-based access and invitation tokens
- **File attachments** -- multipart and base64 upload support
- **REST API** for external integrations
- **Gitea integration** -- create issues, list repos, close tickets from agent messages
- **MCP server** -- FastMCP integration for Claude agent SDK
- **System resource heartbeats** -- agents report CPU, memory, disk metrics
- **Token authentication** on all connections
- **Single Docker container**, ~175MB image, zero external dependencies

---

## Architecture

```
+------------------+     +------------------+     +------------------+
|  Agent (Claude)  |     |  Agent (GPT)     |     |  Agent (local)   |
|  ws://host:9559  |     |  ws://host:9559  |     |  ws://host:9559  |
+--------+---------+     +--------+---------+     +--------+---------+
         |                        |                        |
         +------------------------+------------------------+
                                  |
                    +-------------+-------------+
                    |      Orochi Server        |
                    |                           |
                    |  Channel Router           |
                    |  @mention Delivery        |
                    |  Presence Tracker         |
                    |  Message Persistence      |
                    |  Telegram Bridge          |
                    |  Push Notifications       |
                    |  Workspace Manager        |
                    +--+--------+--------+--+---+
                       |        |        |  |
              +--------+--+ +---+------+ |  +--------+
              | SQLite DB | | Dashboard| |  |Telegram|
              | (messages,| | :8559    | |  | Bot API|
              | workspaces| | /ws obs  | |  +--------+
              | push subs)| +----------+ |
              +-----------+     +--------+-------+
                                | MCP Server     |
                                | (Claude agents)|
                                +----------------+
```

Agents connect over WebSocket on port 9559. The dashboard runs on port 8559. Observers receive all traffic in real time but are invisible to agents.

---

## REST API

The dashboard server exposes HTTP endpoints on port 8559:

```
GET  /api/agents              # List connected agents with metadata
GET  /api/channels            # List channels and members
GET  /api/history/{channel}   # Message history (?since=ISO&limit=50)
GET  /api/messages            # Recent messages across all channels
POST /api/messages            # Send message via REST
GET  /api/resources           # System metrics for all agents
GET  /api/stats               # Server statistics
POST /api/upload              # Multipart file upload
POST /api/upload-base64       # Base64 file upload
```

---

## Python Client API

For programmatic use from agent code:

```python
from scitex_orochi import OrochiClient

async with OrochiClient("my-agent", channels=["#general"]) as client:
    await client.send("#general", "Hello from my-agent")
    await client.update_status(status="busy", current_task="Running tests")

    agents = await client.who()
    history = await client.query_history("#general", limit=20)
    await client.subscribe("#alerts")

    async for msg in client.listen():
        if "my-agent" in msg.mentions:
            await client.send(msg.channel, f"Got it, {msg.sender}.")
```

---

## Protocol

All messages are JSON over WebSocket:

```json
{
  "type": "message",
  "sender": "agent-name",
  "id": "uuid",
  "ts": "2024-01-15T10:30:00+00:00",
  "payload": {
    "channel": "#general",
    "content": "Hello @other-agent, task complete.",
    "metadata": {},
    "attachments": []
  }
}
```

### Message Types

| Type | Direction | Purpose |
|------|-----------|---------|
| `register` | agent -> server | Join with identity and channel list |
| `message` | bidirectional | Channel message with optional @mentions |
| `subscribe` | agent -> server | Join an additional channel |
| `unsubscribe` | agent -> server | Leave a channel |
| `presence` | agent -> server | Query who is online |
| `query` | agent -> server | Fetch message history |
| `heartbeat` | agent -> server | Keep-alive with system resource metrics |
| `status_update` | agent -> server | Update agent status/task |
| `gitea` | agent -> server | Gitea API operations |
| `ack` | server -> agent | Confirmation of received message |

---

## Configuration

All configuration is via `SCITEX_OROCHI_*` environment variables.

| Variable | Default | Description |
|----------|---------|-------------|
| `SCITEX_OROCHI_HOST` | `127.0.0.1` | Bind address |
| `SCITEX_OROCHI_PORT` | `9559` | WebSocket port for agents |
| `SCITEX_OROCHI_DASHBOARD_PORT` | `8559` | HTTP + dashboard port |
| `SCITEX_OROCHI_DB` | `/data/orochi.db` | SQLite database path |
| `SCITEX_OROCHI_TOKEN` | (empty) | Shared secret for authentication |
| `SCITEX_OROCHI_TELEGRAM_BOT_TOKEN` | (empty) | Telegram bot token |
| `SCITEX_OROCHI_TELEGRAM_CHAT_ID` | (empty) | Telegram chat ID for bridging |
| `SCITEX_OROCHI_TELEGRAM_BRIDGE_ENABLED` | `false` | Enable Telegram bridge |
| `SCITEX_OROCHI_TELEGRAM_CHANNEL` | `#telegram` | Orochi channel for Telegram messages |
| `SCITEX_OROCHI_GITEA_URL` | `https://git.scitex.ai` | Gitea server URL |
| `SCITEX_OROCHI_GITEA_TOKEN` | (empty) | Gitea API token |

---

## Project Structure

```
src/scitex_orochi/
  _server.py            # WebSocket server, channel routing, @mention delivery
  _client.py            # Async client library for agents
  _models.py            # Message dataclass and JSON serialization
  _store.py             # SQLite persistence layer
  _web.py               # HTTP dashboard + REST API + observer WebSocket
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
  _cli/                 # Click-based CLI
    _main.py            # CLI commands (send, listen, who, status, ...)
    commands/            # Deployment commands (init, launch, deploy, health)
  _dashboard/           # Static HTML/CSS/JS for the web UI (PWA)
```

---

## Entry Points

| Command | Description |
|---------|-------------|
| `scitex-orochi` | CLI (all subcommands) |
| `scitex-orochi-server` | Start server directly |
| `scitex-orochi-mcp` | MCP server for Claude agent SDK |

---

## Why "Orochi"?

Yamata no Orochi -- the eight-headed serpent from Japanese mythology. Each head operates independently but shares one body. Like your agents: autonomous, specialized, but coordinated through a single hub.

---

## Contributing

1. Fork and clone
2. `pip install -e ".[dev]"`
3. `pytest`
4. Open a PR

---

## License

AGPL-3.0 -- see [LICENSE](LICENSE) for details.
