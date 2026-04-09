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
import {
  handleReply,
  handleHistory,
  handleReact,
  handleStatus,
  handleSubagents,
  handleTask,
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
if ((process.env.CLAUDE_AGENT_ROLE || "").toLowerCase() === "telegram") {
  console.error(
    "[scitex-orochi] BLOCKED: telegram agent must not run Orochi MCP channel",
  );
  process.exit(1);
}

// Safety: block if Telegram bot token env vars are present (indicates a Telegram agent session)
// Exception: if SCITEX_OROCHI_TOKEN is explicitly set, this MCP server was
// intentionally configured (e.g., via agent-container) and should run despite
// telegram vars leaking from the parent environment.
const _telegramToken =
  process.env.TELEGRAM_BOT_TOKEN ||
  process.env.SCITEX_NOTIFICATION_TELEGRAM_BOT_TOKEN;
if (_telegramToken && !process.env.SCITEX_OROCHI_TOKEN) {
  console.error(
    "[scitex-orochi] WARNING: Telegram bot token detected in environment",
  );
  console.error(
    "[scitex-orochi] BLOCKED: Orochi MCP channel refuses to run alongside Telegram bot",
  );
  console.error(
    "[scitex-orochi] (Set SCITEX_OROCHI_TOKEN to override this guard)",
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

    /* Attachments may arrive under three shapes depending on sender path:
     *  - msg.metadata.attachments (current hub flat broadcast)
     *  - msg.attachments (some clients)
     *  - payload.attachments (legacy nested format)
     * Normalize into one list and rewrite relative URLs into absolute
     * ones so the receiving agent can fetch them directly with curl/Read. */
    const rawAttachments =
      (msg.metadata && msg.metadata.attachments) ||
      msg.attachments ||
      payload.attachments ||
      [];
    const hubBase = httpBase || "";
    const attachments = (rawAttachments as Array<{ url?: string; filename?: string; mime_type?: string }>).map(
      (a) => {
        const u = a.url || "";
        const abs = u.startsWith("http") ? u : hubBase.replace(/\/$/, "") + u;
        return { ...a, url: abs };
      },
    );
    const attachmentInfo =
      attachments.length > 0
        ? `\n[Attachments: ${attachments
            .map((a) => `${a.filename || "file"} -> ${a.url}`)
            .join(", ")}]`
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
    name: "task",
    description:
      "Update this agent's current intellectual task so users can see what it is thinking about in real time in the Activity tab. Call this whenever picking up a new piece of work — even for work that has no shell signature (reading, designing, reviewing).",
    inputSchema: {
      type: "object" as const,
      properties: {
        task: {
          type: "string",
          description:
            "Short description of the current work (<= 200 chars). Include issue refs like #142 when relevant.",
        },
      },
      required: ["task"],
    },
  },
  {
    name: "subagents",
    description:
      "Report this agent's current subagent tree to Orochi so the Activity tab renders them nested under this agent. Pass the full list on every call (full-replace semantics).",
    inputSchema: {
      type: "object" as const,
      properties: {
        subagents: {
          type: "array",
          description:
            "Current subagents. Each item: {name, task, status?}. status is one of running|done|failed (default running).",
          items: {
            type: "object",
            properties: {
              name: { type: "string" },
              task: { type: "string" },
              status: { type: "string" },
            },
            required: ["name", "task"],
          },
        },
      },
      required: ["subagents"],
    },
  },
  {
    name: "react",
    description:
      "React to an Orochi message with an emoji (toggle semantics). Pass the integer message_id and the emoji character.",
    inputSchema: {
      type: "object" as const,
      properties: {
        message_id: {
          type: ["number", "string"],
          description: "The integer ID of the message to react to.",
        },
        emoji: {
          type: "string",
          description: "The emoji character (e.g. 👍, ❌, 👀).",
        },
      },
      required: ["message_id", "emoji"],
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
  if (name === "react") return handleReact(args as any);
  if (name === "subagents") return handleSubagents(conn, args as any);
  if (name === "task") return handleTask(conn, args as any);
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
