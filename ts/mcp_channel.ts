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

import WebSocket from "ws";
import {
  OROCHI_AGENT,
  OROCHI_CHANNELS,
  OROCHI_MODEL,
  OROCHI_TOKEN,
  buildHttpBase,
  buildWsUrl,
  maskUrl,
} from "./src/config.js";
import { addMessage } from "./src/message_buffer.js";
import {
  handleContext,
  handleHealth,
  handleReply,
  handleHistory,
  handleReact,
  handleStatus,
  handleSubagents,
  handleTask,
} from "./src/tools.js";
import { hostname } from "os";

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
// Exception: if SCITEX_OROCHI_TOKEN is explicitly set, this MCP server was
// intentionally configured (e.g., via agent-container) and should run despite
// telegram vars leaking from the parent environment.
const _telegramToken = process.env.SCITEX_OROCHI_TELEGRAM_BOT_TOKEN;
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
// GitHub issue title cache so `#NNN` in inbound messages can be expanded to
// `#NNN (title)` before reaching the agent — same as the dashboard render.
// ---------------------------------------------------------------------------
const _issueTitleCache: Map<string, string> = new Map();
let _issueCacheLastFetch = 0;
const _ISSUE_CACHE_TTL_MS = 5 * 60 * 1000;

async function refreshIssueTitleCache(): Promise<void> {
  const now = Date.now();
  if (now - _issueCacheLastFetch < _ISSUE_CACHE_TTL_MS) return;
  try {
    const url = `${buildHttpBase()}/api/github/issues${OROCHI_TOKEN ? `?token=${OROCHI_TOKEN}&state=all` : "?state=all"}`;
    const resp = await fetch(url);
    if (!resp.ok) return;
    const issues = (await resp.json()) as Array<{
      number?: number;
      title?: string;
    }>;
    for (const i of issues) {
      if (i && i.number && i.title)
        _issueTitleCache.set(String(i.number), i.title);
    }
    _issueCacheLastFetch = now;
  } catch (_) {
    /* ignore — next message will retry */
  }
}

function decorateIssueRefs(text: string): string {
  return text.replace(/(^|[^\w\/])#(\d+)\b/g, (match, lead, num) => {
    const title = _issueTitleCache.get(num);
    if (!title) return match;
    return `${lead}#${num} (${title})`;
  });
}

// ---------------------------------------------------------------------------
// Direct WebSocket connection (replaces OrochiConnection class).
// The class wrapper was suspected of interfering with idle-state
// MCP notifications -- this minimal approach mirrors the working
// /tmp/test-channel-ws.ts pattern.
// ---------------------------------------------------------------------------
import { appendFileSync } from "fs";
const _dbg = (s: string) => {
  try {
    appendFileSync("/tmp/orochi-mcp-debug.log", s + "\n");
  } catch {}
};

// Dedup: track recently delivered message IDs to prevent duplicate notifications
const _deliveredIds = new Set<string | number>();

// Lightweight adapter that satisfies the OrochiConnection interface
// expected by tools.ts (isConnected, state, send, reconnectAttempts, etc.)
let _ws: WebSocket | null = null;
const conn = {
  state: "disconnected" as string,
  lastConnectedAt: null as Date | null,
  totalReconnects: 0,
  reconnectAttempts: 0,
  get isConnected(): boolean {
    return _ws !== null && _ws.readyState === WebSocket.OPEN;
  },
  get lastPongAgeMs(): number | null {
    return null; // no ping/pong in minimal mode
  },
  get socket(): WebSocket | null {
    return _ws;
  },
  send(data: string): boolean {
    if (!this.isConnected) return false;
    try {
      _ws!.send(data);
      return true;
    } catch (_) {
      return false;
    }
  },
  connect(): void {
    const wsUrl = buildWsUrl();
    _dbg(`ws connecting to ${maskUrl(wsUrl)}`);
    conn.state = "connecting";

    _ws = new WebSocket(wsUrl);

    _ws.on("open", () => {
      conn.state = "connected";
      conn.lastConnectedAt = new Date();
      conn.reconnectAttempts = 0;
      console.error(`[orochi] ws connected as ${OROCHI_AGENT}`);
      _dbg(`ws open`);

      // Register with the hub
      _ws!.send(
        JSON.stringify({
          type: "register",
          sender: OROCHI_AGENT,
          payload: {
            channels: OROCHI_CHANNELS,
            machine: hostname(),
            role: "claude-code",
            model: OROCHI_MODEL,
            agent_id: `${OROCHI_AGENT}@${hostname()}`,
            icon: process.env.SCITEX_OROCHI_ICON || "",
            icon_emoji: process.env.SCITEX_OROCHI_ICON_EMOJI || "",
            icon_text: process.env.SCITEX_OROCHI_ICON_TEXT || "",
            project: "",
          },
        }),
      );
    });

    _ws.on("message", async (data: Buffer) => {
      const raw = data.toString();
      try {
        _dbg(`ws recv: ${raw.slice(0, 200)}`);
        const msg = JSON.parse(raw);

        // Thread replies and reaction updates -> rewrite to message type
        if (msg.type === "thread_reply") {
          const parentId = msg.parent_id ?? msg.parent ?? "?";
          msg.type = "message";
          msg.text = `\u21b3 reply to msg#${parentId}: ${msg.text || msg.content || ""}`;
        } else if (msg.type === "reaction_update") {
          const targetId = msg.message_id ?? msg.target ?? "?";
          const emoji = msg.emoji || "?";
          const action = msg.action || (msg.added ? "added" : "removed");
          msg.type = "message";
          msg.text = `${action === "removed" ? "\u2796" : "\u2795"} ${emoji} on msg#${targetId}`;
          msg.sender = msg.actor || msg.sender || "unknown";
        } else if (msg.type !== "message") {
          return;
        }

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

        addMessage({
          id: msg.id ?? payload.id ?? null,
          channel: channel,
          sender: sender,
          content: content,
          ts: msg.ts || new Date().toISOString(),
          metadata: msg.metadata || payload.metadata || {},
        });

        if (sender === OROCHI_AGENT || !content) {
          _dbg(
            `skipped: sender=${sender} agent=${OROCHI_AGENT} content=${!!content}`,
          );
          return;
        }

        // Dedup
        const msgId = msg.id ?? payload.id;
        if (msgId != null) {
          if (_deliveredIds.has(msgId)) {
            _dbg(`dedup: skipping duplicate msg ${msgId}`);
            return;
          }
          _deliveredIds.add(msgId);
          if (_deliveredIds.size > 100) {
            const iter = _deliveredIds.values();
            for (let i = 0; i < 50; i++) iter.next();
            const keep = new Set<string | number>();
            for (const v of iter) keep.add(v);
            _deliveredIds.clear();
            for (const v of keep) _deliveredIds.add(v);
          }
        }

        _dbg(
          `delivering: sender=${sender} channel=${channel} content=${content.slice(0, 50)} id=${msgId}`,
        );

        // Attachment normalization
        const rawAttachments =
          (msg.metadata && msg.metadata.attachments) ||
          msg.attachments ||
          payload.attachments ||
          [];
        const hubBase = `http://${process.env.SCITEX_OROCHI_HOST || "localhost"}:${process.env.SCITEX_OROCHI_PORT || "8559"}`;
        const attachments = (
          rawAttachments as Array<{
            url?: string;
            filename?: string;
            mime_type?: string;
          }>
        ).map((a) => {
          const u = a.url || "";
          const abs = u.startsWith("http")
            ? u
            : hubBase.replace(/\/$/, "") + u;
          return { ...a, url: abs };
        });
        const attachmentInfo =
          attachments.length > 0
            ? `\n[Attachments: ${attachments
                .map((a) => `${a.filename || "file"} -> ${a.url}`)
                .join(", ")}]`
            : "";

        refreshIssueTitleCache();
        const decoratedContent = decorateIssueRefs(content);

        const notifContent = `${decoratedContent}${attachmentInfo}`;
        // Meta values must all be strings — Claude Code ignores
        // notifications where meta contains non-string values (numbers, null).
        const notifMeta: Record<string, string> = {
          chat_id: channel || "#general",
          user: sender,
          ts: msg.ts || new Date().toISOString(),
        };
        const msgIdVal = msg.id ?? payload.id;
        if (msgIdVal != null) notifMeta.msg_id = String(msgIdVal);

        // Retry with exponential backoff (pattern from official Discord plugin).
        // Claude Code can silently drop notifications; retrying mitigates this.
        const notifPayload = {
          method: "notifications/claude/channel" as const,
          params: { content: notifContent, meta: notifMeta },
        };
        const delays = [0, 500, 1000];
        let delivered = false;
        for (let attempt = 0; attempt < delays.length; attempt++) {
          if (attempt > 0) await new Promise((r) => setTimeout(r, delays[attempt]));
          try {
            await mcp.notification(notifPayload);
            _dbg(`notification sent OK (attempt ${attempt + 1}): ${channel} ${sender}`);
            delivered = true;
            break;
          } catch (retryErr) {
            _dbg(`notification attempt ${attempt + 1} failed: ${retryErr}`);
          }
        }
        if (!delivered) {
          console.error(`[orochi] all notification attempts failed for ${channel} ${sender}`);
        }
      } catch (e) {
        const errMsg = e instanceof Error ? e.message : String(e);
        _dbg(`error: ${errMsg}`);
        console.error(`[orochi] message handler error: ${errMsg}`);
      }
    });

    _ws.on("close", (code: number, reason: Buffer) => {
      const reasonStr = reason?.toString() || "unknown";
      console.error(
        `[orochi] ws disconnected (code=${code}, reason=${reasonStr})`,
      );
      _dbg(`ws close code=${code}`);
      conn.state = "disconnected";
      _ws = null;
      // Simple reconnect after 3s
      conn.reconnectAttempts++;
      conn.totalReconnects++;
      setTimeout(() => conn.connect(), 3000);
    });

    _ws.on("error", (err) => {
      console.error("[orochi] ws error:", err.message);
      _dbg(`ws error: ${err.message}`);
      // close event will fire after error, triggering reconnect
    });
  },
};

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
    name: "health",
    description:
      "Record a health diagnosis for an agent (caduceus primary caller). Use for real-time Agents tab status. Status values: healthy, idle, stale, stuck_prompt, dead, ghost, remediating, unknown.",
    inputSchema: {
      type: "object" as const,
      properties: {
        agent: {
          type: "string",
          description: "Target agent name (exact match)",
        },
        status: {
          type: "string",
          description:
            "healthy|idle|stale|stuck_prompt|dead|ghost|remediating|unknown",
        },
        reason: {
          type: "string",
          description: "Short explanation (<=200 chars)",
        },
        source: {
          type: "string",
          description: "Reporter name (defaults to self)",
        },
        updates: {
          type: "array",
          description: "Bulk: list of {agent,status,reason?,source?}",
          items: {
            type: "object",
            properties: {
              agent: { type: "string" },
              status: { type: "string" },
              reason: { type: "string" },
              source: { type: "string" },
            },
            required: ["agent", "status"],
          },
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
    name: "context",
    description:
      "Get the Claude Code context window usage percentage by reading the screen session's statusline.",
    inputSchema: {
      type: "object" as const,
      properties: {
        screen_name: {
          type: "string",
          description:
            "GNU screen session name to read from (defaults to this agent's name).",
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
  if (name === "reply") return handleReply(conn as any, args as any);
  if (name === "history") return handleHistory(args as any);
  if (name === "react") return handleReact(args as any);
  if (name === "subagents") return handleSubagents(conn as any, args as any);
  if (name === "task") return handleTask(conn as any, args as any);
  if (name === "health") return handleHealth(args as any);
  if (name === "context") return handleContext(args as any);
  if (name === "status") return handleStatus(conn as any);
  throw new Error(`Unknown tool: ${name}`);
});

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
