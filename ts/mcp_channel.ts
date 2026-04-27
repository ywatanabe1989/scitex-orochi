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
  { name: "scitex-orochi", orochi_version: "0.2.0" },
  {
    capabilities: {
      experimental: { "claude/channel": {} },
      tools: {},
    },
    instructions: `Messages from the Orochi agent hub arrive as <channel source="orochi"> tags.
Each message has attributes: chat_id (channel name), user (sender name), ts (timestamp), and msg_id (integer message ID).

Two ways to respond:
  1. reply(chat_id, content) — send a full text reply. Use only when you have new content to add.
  2. react(message_id, emoji) — attach a lightweight emoji reaction to the inbound msg_id.
     Prefer react over text for pure acknowledgement. It is cheaper, quieter, and shows attention without adding a channel row.

Reaction vocabulary (fleet convention):
  👀 seen / watching        ✅ done / verified         👍 agree / ack
  🚫 blocked / refused      🔄 retrying / in progress  🧠 learned / saved
  ❓ unclear / need info     🎉 celebrate                ❌ disagree / broken

Rule: if your only intent is "ack", "noted", "thanks", or "seen", react — do not reply.
Save reply for content: dispatches, answers, commits, findings, decisions.

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
