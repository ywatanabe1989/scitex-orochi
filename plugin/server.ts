import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import WebSocket from "ws";
import { hostname } from "os";

// Config from env
const OROCHI_HOST = process.env.OROCHI_HOST || "192.168.0.102";
const OROCHI_PORT = parseInt(process.env.OROCHI_PORT || "9559");
const OROCHI_AGENT = process.env.OROCHI_AGENT || `${hostname()}-claude`;
const OROCHI_CHANNELS = (process.env.OROCHI_CHANNELS || "#general")
  .split(",")
  .map((s) => s.trim());
const OROCHI_TOKEN = process.env.OROCHI_TOKEN || "";

const wsUrl = `ws://${OROCHI_HOST}:${OROCHI_PORT}${OROCHI_TOKEN ? `?token=${OROCHI_TOKEN}` : ""}`;

// MCP Server with channel capability
const mcp = new Server(
  { name: "orochi", version: "0.1.0" },
  {
    capabilities: {
      experimental: {
        "claude/channel": {},
      },
      tools: {},
    },
    instructions: `Messages from the Orochi agent hub arrive as <channel source="orochi"> tags.
Each message has attributes: chat_id (channel name), user (sender name), ts (timestamp).
Use the reply tool to send messages back. Pass chat_id from the inbound message.
Orochi is a real-time communication hub for AI agents across different machines.`,
  },
);

let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

function connect() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  try {
    ws = new WebSocket(wsUrl);
  } catch (err) {
    console.error("[orochi] failed to create WebSocket:", err);
    scheduleReconnect();
    return;
  }

  ws.on("open", () => {
    console.error(
      `[orochi] connected to ${OROCHI_HOST}:${OROCHI_PORT} as ${OROCHI_AGENT}`,
    );

    // Register with Orochi server
    const reg = JSON.stringify({
      type: "register",
      sender: OROCHI_AGENT,
      payload: {
        channels: OROCHI_CHANNELS,
        machine: hostname(),
        role: "claude-code",
        agent_id: `${OROCHI_AGENT}@${hostname()}`,
        project: "",
      },
    });
    ws!.send(reg);
  });

  ws.on("message", async (data: Buffer) => {
    try {
      const msg = JSON.parse(data.toString());

      if (msg.type === "message") {
        const payload = msg.payload || {};
        const content =
          payload.content || payload.text || payload.message || "";
        const sender = payload.sender || msg.sender || "unknown";
        const channel = payload.channel || "";

        // Don't echo own messages
        if (sender === OROCHI_AGENT) return;
        // Skip empty messages
        if (!content) return;

        // Push into Claude Code session
        await mcp.notification({
          method: "notifications/claude/channel",
          params: {
            content: `${content}`,
            meta: {
              chat_id: channel,
              user: sender,
              ts: msg.ts || new Date().toISOString(),
            },
          },
        });
      }
      // Silently handle ack, error, presence, etc.
    } catch (err) {
      // Parse errors are normal for non-JSON messages
    }
  });

  ws.on("close", () => {
    console.error("[orochi] disconnected");
    ws = null;
    scheduleReconnect();
  });

  ws.on("error", (err) => {
    console.error("[orochi] websocket error:", err.message);
  });
}

function scheduleReconnect() {
  if (!reconnectTimer) {
    reconnectTimer = setTimeout(() => {
      console.error("[orochi] reconnecting...");
      connect();
    }, 5000);
  }
}

// Reply tool — send message back to Orochi
mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "reply",
      description:
        "Send a message to an Orochi channel. Pass chat_id from the inbound <channel> tag.",
      inputSchema: {
        type: "object" as const,
        properties: {
          chat_id: {
            type: "string",
            description:
              "The channel to send to (e.g. #general). From the chat_id attribute of the inbound message.",
          },
          text: {
            type: "string",
            description: "The message text to send.",
          },
          reply_to: {
            type: "string",
            description: "Optional: message ID to reply to.",
          },
        },
        required: ["chat_id", "text"],
      },
    },
  ],
}));

mcp.setRequestHandler(CallToolRequestSchema, async (req) => {
  if (req.params.name === "reply") {
    const args = req.params.arguments as {
      chat_id: string;
      text: string;
      reply_to?: string;
    };

    if (!ws || ws.readyState !== WebSocket.OPEN) {
      return {
        content: [{ type: "text", text: "Error: not connected to Orochi" }],
      };
    }

    const msg = JSON.stringify({
      type: "message",
      sender: OROCHI_AGENT,
      payload: {
        channel: args.chat_id,
        content: args.text,
        metadata: args.reply_to ? { reply_to: args.reply_to } : {},
      },
    });
    ws.send(msg);

    return { content: [{ type: "text", text: `sent` }] };
  }

  throw new Error(`Unknown tool: ${req.params.name}`);
});

// Start
connect();
const transport = new StdioServerTransport();
await mcp.connect(transport);
