/**
 * scitex-orochi MCP channel bridge -- connects Claude Code to the Orochi hub.
 *
 * v0.2.0: WSS support, ping/pong stale detection, connection state tracking.
 *
 * Thin orchestrator. The work is split across:
 *   - mcp_channel/guards.ts      env-var boot guards
 *   - mcp_channel/heartbeat.ts   /api/agents/register heartbeat pump
 *   - mcp_channel/dispatch.ts    inbound WS message → MCP notification
 *   - mcp_channel/connection.ts  WebSocket connect/reconnect + `conn` adapter
 *   - mcp_channel/handlers.ts    MCP ListTools / CallTool dispatch table
 *
 * Existing helper modules: src/config.ts, src/connection.ts, src/metrics.ts,
 * src/tools.ts, src/message_buffer.ts, src/issue_cache.ts, src/tool_defs.ts.
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { OROCHI_AGENT, buildWsUrl, maskUrl } from "./src/config.js";

import { applyBootGuards } from "./mcp_channel/guards.js";
import { conn, attachMcp } from "./mcp_channel/connection.js";
import { registerMcpHandlers } from "./mcp_channel/handlers.js";

applyBootGuards();

// ---------------------------------------------------------------------------
// MCP Server
// ---------------------------------------------------------------------------
const mcp = new Server(
  { name: "scitex-orochi", version: "0.2.0" },
  {
    capabilities: {
      experimental: { "claude/channel": {} },
      tools: {},
    },
    instructions: `Messages from the Orochi agent hub arrive as <channel source="orochi"> tags.
Each message has attributes: chat_id (channel name), user (sender name), ts (timestamp).
Use the reply tool to send messages back. Pass chat_id from the inbound message.
Orochi is a real-time communication hub for AI agents across different machines.`,
  },
);

attachMcp(mcp);
registerMcpHandlers(mcp);

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------
const wsUrl = buildWsUrl();
console.error(
  `[orochi] starting push client v0.2.0 (agent=${OROCHI_AGENT}, url=${maskUrl(wsUrl)})`,
);
const transport = new StdioServerTransport();
await mcp.connect(transport);
console.error("[orochi] MCP stdio connected, starting WebSocket...");
conn.connect();
