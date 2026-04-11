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

import {
  refreshIssueTitleCache,
  decorateIssueRefs,
} from "./src/issue_cache.js";
import { TOOL_DEFS } from "./src/tool_defs.js";

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
            role: process.env.SCITEX_OROCHI_ROLE || "claude-code",
            model: OROCHI_MODEL,
            agent_id: `${OROCHI_AGENT}@${hostname()}`,
            icon: process.env.SCITEX_OROCHI_ICON || "",
            icon_emoji: process.env.SCITEX_OROCHI_ICON_EMOJI || "",
            icon_text: process.env.SCITEX_OROCHI_ICON_TEXT || "",
            project: process.env.SCITEX_OROCHI_PROJECT || "",
            workdir: process.cwd(),
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
          const abs = u.startsWith("http") ? u : hubBase.replace(/\/$/, "") + u;
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
          if (attempt > 0)
            await new Promise((r) => setTimeout(r, delays[attempt]));
          try {
            await mcp.notification(notifPayload);
            _dbg(
              `notification sent OK (attempt ${attempt + 1}): ${channel} ${sender}`,
            );
            delivered = true;
            break;
          } catch (retryErr) {
            _dbg(`notification attempt ${attempt + 1} failed: ${retryErr}`);
          }
        }
        if (!delivered) {
          console.error(
            `[orochi] all notification attempts failed for ${channel} ${sender}`,
          );
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

// Tool definitions imported from src/tool_defs.ts

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
