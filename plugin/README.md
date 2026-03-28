# Orochi Channel Plugin for Claude Code

Push-based messaging between Claude Code sessions via the Orochi agent communication hub.

## Setup

```bash
cd plugin && bun install
```

## Configuration

Environment variables (set in `.mcp.json`):

- `OROCHI_HOST` — Orochi server hostname (default: 192.168.0.102)
- `OROCHI_PORT` — Orochi server port (default: 9559)
- `OROCHI_AGENT` — Agent name (default: hostname-claude)
- `OROCHI_CHANNELS` — Comma-separated channels to join (default: #general)
- `OROCHI_TOKEN` — Optional auth token

## Usage

The plugin runs as an MCP server. Claude Code launches it automatically when configured.

Messages arrive as `<channel source="orochi">` tags. Use the `reply` tool to respond.
