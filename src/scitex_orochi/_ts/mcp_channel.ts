/**
 * scitex-orochi MCP channel bridge -- connects Claude Code to the Orochi hub.
 *
 * v0.2.0: WSS support, ping/pong stale detection, connection state tracking.
 * Modules: src/config.ts, src/connection.ts, src/orochi_metrics.ts, src/tools.ts
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

import { OROCHI_AGENT, buildWsUrl, maskUrl } from "./src/config.js";
import { OrochiConnection } from "./src/connection.js";
import {
  handleReply,
  handleHistory,
  handleStatus,
  handleSubscribe,
  handleUnsubscribe,
  handleChannelInfo,
} from "./src/tools.js";

// Unified truthy check for env var guards
const TRUTHY = new Set(["true", "1", "yes", "enable", "enabled"]);
function isTruthy(val?: string): boolean {
  return TRUTHY.has((val || "").toLowerCase());
}

// Generic disable switch
if (isTruthy(process.env.SCITEX_OROCHI_DISABLE)) {
  console.error("[scitex-orochi] Disabled via SCITEX_OROCHI_DISABLE");
  process.exit(0);
}

// Zero-trust: telegram agents must never run this MCP server
if ((process.env.SCITEX_OROCHI_AGENT_ROLE || "").toLowerCase() === "telegram") {
  console.error(
    "[scitex-orochi] BLOCKED: telegram agent must not run Orochi MCP channel",
  );
  process.exit(1);
}

// Safety: block if Telegram bot token env vars are present (indicates a Telegram agent session)
const _telegramToken = process.env.SCITEX_OROCHI_TELEGRAM_BOT_TOKEN;
if (_telegramToken) {
  console.error(
    "[scitex-orochi] WARNING: Telegram bot token detected in environment",
  );
  console.error(
    "[scitex-orochi] BLOCKED: Orochi MCP channel refuses to run alongside Telegram bot",
  );
  process.exit(1);
}

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

// ---------------------------------------------------------------------------
// WebSocket connection with message routing to MCP
// ---------------------------------------------------------------------------
const conn = new OrochiConnection(async (raw: string) => {
  try {
    const msg = JSON.parse(raw);

    // todo#46 — hub→agent JSON ping. Echo the original ts back so the
    // hub can compute RTT. Keep the branch first so ping handling is
    // not blocked by any later message-type routing.
    if (msg.type === "ping") {
      const sentTs =
        typeof msg.ts === "number"
          ? msg.ts
          : typeof msg?.payload?.ts === "number"
            ? msg.payload.ts
            : null;
      if (sentTs !== null) {
        conn.send(JSON.stringify({ type: "pong", payload: { ts: sentTs } }));
      }
      return;
    }

    if (msg.type !== "message") return;

    const payload = msg.payload || {};
    const content = payload.content || payload.text || payload.message || "";
    const sender = payload.sender || msg.sender || "unknown";
    const channel = payload.channel || "";

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
  {
    name: "subscribe",
    description:
      "Subscribe this agent to an Orochi channel. Persists server-side so the subscription survives reboot.",
    inputSchema: {
      type: "object" as const,
      properties: {
        channel: {
          type: "string",
          description: "Channel name (e.g. #general).",
        },
      },
      required: ["channel"],
    },
  },
  {
    name: "unsubscribe",
    description:
      "Unsubscribe this agent from an Orochi channel. Removes the persisted subscription row.",
    inputSchema: {
      type: "object" as const,
      properties: {
        channel: {
          type: "string",
          description: "Channel name (e.g. #general).",
        },
      },
      required: ["channel"],
    },
  },
  {
    name: "channel_info",
    description:
      "Fetch a channel's human-authored description (topic) so the agent understands the channel's purpose. Returns { name, description }.",
    inputSchema: {
      type: "object" as const,
      properties: {
        channel: {
          type: "string",
          description: "Channel name (e.g. #general).",
        },
      },
      required: ["channel"],
    },
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
  if (name === "subscribe") return handleSubscribe(conn, args as any);
  if (name === "unsubscribe") return handleUnsubscribe(conn, args as any);
  if (name === "channel_info") return handleChannelInfo(args as any);
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
