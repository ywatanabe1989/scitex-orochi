/**
 * scitex-orochi MCP channel bridge -- connects Claude Code to the Orochi hub.
 *
 * v0.2.0: WSS support, ping/pong stale detection, connection state tracking.
 * Modules: src/config.ts, src/connection.ts, src/metrics.ts, src/tools.ts
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

import { OROCHI_AGENT, buildWsUrl, maskUrl } from "./src/config.js";
import { OrochiConnection } from "./src/connection.js";
import { handleReply, handleHistory, handleStatus } from "./src/tools.js";

// Zero-trust: telegram agents must never run this MCP server
if (process.env.CLAUDE_AGENT_ROLE === "telegram") {
  console.error(
    "[scitex-orochi] BLOCKED: telegram agent must not run Orochi MCP channel",
  );
  process.exit(1);
}

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

// ---------------------------------------------------------------------------
// WebSocket connection with message routing to MCP
// ---------------------------------------------------------------------------
const conn = new OrochiConnection(async (raw: string) => {
  try {
    const msg = JSON.parse(raw);
    if (msg.type !== "message") return;

    // Hub sends flat messages: {type, sender, channel, text, ts, metadata}
    // Also support legacy nested payload format for backward compatibility
    const payload = msg.payload || {};
    const content =
      msg.text ||
      msg.content ||
      payload.content ||
      payload.text ||
      payload.message ||
      "";
    const sender = msg.sender || payload.sender || "unknown";
    const channel = msg.channel || payload.channel || "";

    if (sender === OROCHI_AGENT || !content) return;

    const attachments = payload.attachments || [];
    const attachmentInfo =
      attachments.length > 0
        ? `\n[Attachments: ${(attachments as Array<{ url: string }>).map((a) => a.url).join(", ")}]`
        : "";

    await mcp.notification({
      method: "notifications/claude/channel",
      params: {
        content: `${content}${attachmentInfo}`,
        meta: {
          chat_id: channel,
          user: sender,
          ts: msg.ts || new Date().toISOString(),
        },
      },
    });
  } catch (_) {
    // Parse errors are normal for non-JSON frames
  }
});

// ---------------------------------------------------------------------------
// Tool definitions
// ---------------------------------------------------------------------------
const TOOL_DEFS = [
  {
    name: "reply",
    description:
      "Send a message to an Orochi channel. Pass chat_id from the inbound <channel> tag.",
    inputSchema: {
      type: "object" as const,
      properties: {
        chat_id: {
          type: "string",
          description: "The channel to send to (e.g. #general).",
        },
        text: { type: "string", description: "The message text to send." },
        reply_to: {
          type: "string",
          description: "Optional: message ID to reply to.",
        },
        files: {
          type: "array",
          items: { type: "string" },
          description: "Optional: absolute file paths to attach.",
        },
      },
      required: ["chat_id", "text"],
    },
  },
  {
    name: "history",
    description: "Get recent message history from an Orochi channel.",
    inputSchema: {
      type: "object" as const,
      properties: {
        channel: {
          type: "string",
          description: "Channel name (default: #general).",
        },
        limit: {
          type: "number",
          description: "Max messages to return (default: 10).",
        },
      },
    },
  },
  {
    name: "status",
    description: "Get current Orochi connection status and diagnostics.",
    inputSchema: { type: "object" as const, properties: {} },
  },
];

mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: TOOL_DEFS,
}));

mcp.setRequestHandler(CallToolRequestSchema, async (req) => {
  const { name, arguments: args } = req.params;
  if (name === "reply") return handleReply(conn, args as any);
  if (name === "history") return handleHistory(args as any);
  if (name === "status") return handleStatus(conn);
  throw new Error(`Unknown tool: ${name}`);
});

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------
const wsUrl = buildWsUrl();
console.error(
  `[orochi] starting push client v0.2.0 (agent=${OROCHI_AGENT}, url=${maskUrl(wsUrl)})`,
);
conn.connect();
const transport = new StdioServerTransport();
await mcp.connect(transport);
