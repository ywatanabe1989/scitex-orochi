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
  OROCHI_MODEL,
  OROCHI_TOKEN,
  buildHttpBase,
  buildWsUrl,
  maskUrl,
} from "./src/config.js";

import { addMessage } from "./src/message_buffer.js";
import { spawnSync } from "child_process";
import {
  handleContext,
  handleDmList,
  handleDmOpen,
  handleDownloadMedia,
  handleHealth,
  handleReply,
  handleHistory,
  handleSubscribe,
  handleUnsubscribe,
  handleConnectivityMatrix,
  handleReact,
  handleRsyncMedia,
  handleRsyncStatus,
  handleSidecarStatus,
  handleStatus,
  handleSelfCommand,
  handleSubagents,
  handleTask,
  handleUploadMedia,
  handleExportChannel,
} from "./src/tools.js";
import { hostname, homedir } from "os";
import { readFileSync, existsSync } from "fs";
import { join } from "path";

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

// ---------------------------------------------------------------------------
// Registry heartbeat — thin pump.
//
// The sidecar shells out to
//     ~/.scitex/orochi/scripts/agent_meta.py <agent>
// which reads the live Claude Code session jsonl transcript and emits
// claude-hud-style metadata (alive, subagents, context_pct, current_tool,
// last_activity, model, ...) as a single JSON line. The resulting dict is
// spread into the hub heartbeat payload.
//
// Historical note: this used to call `scitex-agent-container status
// <agent> --json` instead, but most fleet agents are launched directly via
// tmux + raw `claude` (not via `scitex-agent-container start`), so they are
// invisible to scitex-agent-container's own registry. The status command
// returned `{"error": "Agent X not found in registry"}` with rc=1 for every
// such agent, the spawn was treated as a hard failure, and pushRegistryHeartbeat
// returned without ever populating the hub's current_task / subagents /
// context_pct fields. The Activity tab then rendered "no task / 0 subs / no
// ctx" for everyone — exactly the symptom ywatanabe flagged at msg#6382. The
// agent_meta.py path bypasses the broken registry lookup entirely (todo#155).
// ---------------------------------------------------------------------------
async function pushRegistryHeartbeat(): Promise<void> {
  if (process.env.SCITEX_OROCHI_REGISTRY_DISABLE === "1") return;
  if (!OROCHI_TOKEN) {
    _dbg("heartbeat: no OROCHI_TOKEN, skipping");
    return;
  }
  const agentMetaPath = join(
    homedir(),
    ".scitex",
    "orochi",
    "scripts",
    "agent_meta.py",
  );
  let meta: Record<string, unknown> = {};
  try {
    // Use .venv python, not system python (ywatanabe msg#12584)
    const venvPython = join(homedir(), ".venv", "bin", "python3");
    const python = existsSync(venvPython) ? venvPython : "python3";
    const result = spawnSync(python, [agentMetaPath, OROCHI_AGENT], {
      encoding: "utf-8",
      timeout: 5000,
    });
    if (result.status !== 0) {
      console.error(
        `[orochi-heartbeat] agent_meta.py failed: ${(result.stderr || "").slice(0, 200)}`,
      );
      _dbg(`heartbeat: agent_meta rc=${result.status}`);
      return;
    }
    meta = JSON.parse(result.stdout);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[orochi-heartbeat] agent_meta spawn failed: ${msg}`);
    _dbg(`heartbeat: spawn err ${msg}`);
    return;
  }

  // agent_meta.py field names → hub /api/agents/register field names.
  // The hub renderer (activity-tab.js) reads `current_task`,
  // `subagent_count`, `context_pct`, `model`. agent_meta.py emits
  // `current_tool`, `subagents`, `context_pct`, `model`. Translate.
  const currentTool = (meta["current_tool"] as string | undefined) || "";
  const subagentCount =
    typeof meta["subagents"] === "number"
      ? (meta["subagents"] as number)
      : Array.isArray(meta["subagents"])
        ? (meta["subagents"] as unknown[]).length
        : 0;
  const payload = {
    // Pass the raw meta through too in case downstream consumers want
    // the original field names — but the hub-canonical fields below
    // take precedence in the spread merge.
    ...meta,
    current_task: currentTool,
    subagent_count: subagentCount,
    token: OROCHI_TOKEN,
    name: OROCHI_AGENT,
    agent_id: OROCHI_AGENT,
    role: process.env.SCITEX_OROCHI_ROLE || "agent",
    machine: process.env.SCITEX_OROCHI_MACHINE || hostname() || "",
    multiplexer: process.env.SCITEX_OROCHI_MULTIPLEXER || "tmux",
  };

  const url = `${buildHttpBase().replace(/\/$/, "")}/api/agents/register/`;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      console.error(
        `[orochi-heartbeat] POST ${url} -> ${res.status}: ${txt.slice(0, 200)}`,
      );
      _dbg(`heartbeat failed: ${res.status} ${txt.slice(0, 200)}`);
    } else {
      _dbg(`heartbeat ok: ${OROCHI_AGENT} -> ${maskUrl(url)}`);
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[orochi-heartbeat] fetch error: ${msg}`);
    _dbg(`heartbeat error: ${msg}`);
  }
}

// Lightweight adapter that satisfies the OrochiConnection interface
// expected by tools.ts (isConnected, state, send, reconnectAttempts, etc.)
let _ws: WebSocket | null = null;
let _heartbeatInterval: ReturnType<typeof setInterval> | null = null;
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

      // App-level heartbeat + liveness alarm.
      // Daphne does NOT respond to WebSocket protocol-level ping frames,
      // so we do NOT terminate on missing pong. Instead, if the connection
      // seems dead (send fails), we emit an alarm for healers.
      let _lastSendOk = Date.now();
      let _alarmSent = false;
      const _pingInterval = setInterval(() => {
        if (!_ws || _ws.readyState !== WebSocket.OPEN) {
          clearInterval(_pingInterval);
          return;
        }
        try {
          _ws.send(
            JSON.stringify({
              type: "heartbeat",
              sender: OROCHI_AGENT,
              payload: {},
            }),
          );
          _lastSendOk = Date.now();
          _alarmSent = false;
        } catch {
          // Send failed — hub may be unreachable
          const silentMs = Date.now() - _lastSendOk;
          if (silentMs > 60000 && !_alarmSent) {
            _alarmSent = true;
            console.error(
              `[orochi] ALARM: hub unreachable for ${Math.round(silentMs / 1000)}s — healer should investigate`,
            );
            _dbg(`alarm: hub unreachable ${silentMs}ms`);
            // Notify Claude Code so it can post to #escalation
            try {
              mcp.notification({
                method: "notifications/claude/channel" as const,
                params: {
                  content: `ALARM: Orochi hub unreachable for ${Math.round(silentMs / 1000)}s. WebSocket heartbeat send failing. Healers should check cloudflared and Daphne.`,
                  meta: {
                    chat_id: "#escalation",
                    user: "system",
                    ts: new Date().toISOString(),
                  },
                },
              });
            } catch {}
          }
        }
      }, 30000);
      _ws!.on("close", () => clearInterval(_pingInterval));

      // Registry heartbeat — fire immediately, then every 30s while connected.
      // Stopped in the top-level ws close handler below.
      if (_heartbeatInterval) {
        clearInterval(_heartbeatInterval);
        _heartbeatInterval = null;
      }
      pushRegistryHeartbeat().catch(() => {});
      _heartbeatInterval = setInterval(() => {
        pushRegistryHeartbeat().catch(() => {});
      }, 30000);

      // Read CLAUDE.md from agent definition dir if available
      let claudeMd = "";
      try {
        const agentDefPath = join(
          homedir(),
          ".scitex",
          "orochi",
          "agents",
          OROCHI_AGENT,
          "CLAUDE.md",
        );
        if (existsSync(agentDefPath)) {
          claudeMd = readFileSync(agentDefPath, "utf-8");
        }
      } catch {}

      // Register with the hub
      _ws!.send(
        JSON.stringify({
          type: "register",
          sender: OROCHI_AGENT,
          payload: {
            machine: hostname(),
            role: process.env.SCITEX_OROCHI_ROLE || "claude-code",
            model: OROCHI_MODEL,
            agent_id: `${OROCHI_AGENT}@${hostname()}`,
            icon: process.env.SCITEX_OROCHI_ICON || "",
            icon_emoji: process.env.SCITEX_OROCHI_ICON_EMOJI || "",
            icon_text: process.env.SCITEX_OROCHI_ICON_TEXT || "",
            color: process.env.SCITEX_OROCHI_COLOR || "",
            project: process.env.SCITEX_OROCHI_PROJECT || "",
            workdir: process.cwd(),
            claude_md: claudeMd,
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

        // @mention filtering: only deliver messages addressed to this agent
        const mentions = content.match(/@(\w[\w-]*)/g);
        if (mentions && mentions.length > 0) {
          const mentionedNames = mentions.map((m: string) =>
            m.slice(1).toLowerCase(),
          );
          const myName = OROCHI_AGENT.toLowerCase();
          if (
            !mentionedNames.includes(myName) &&
            !mentionedNames.includes("all")
          ) {
            _dbg(
              `mention-filter: skipping msg for [${mentionedNames.join(",")}], I am ${OROCHI_AGENT}`,
            );
            return;
          }
        }

        _dbg(
          `delivering: sender=${sender} channel=${channel} content=${content.slice(0, 50)} id=${msgId}`,
        );

        // Attachment normalization — wrapped in try/catch so malformed
        // attachment data never crashes the sidecar or drops the message.
        let attachmentInfo = "";
        try {
          const rawAttachments =
            (msg.metadata && msg.metadata.attachments) ||
            msg.attachments ||
            payload.attachments ||
            [];
          // Derive hubBase from SCITEX_OROCHI_URL (public wss://host/...) so
          // agent notifications carry a browser-reachable absolute URL rather
          // than the internal localhost:8559 default. Fall back to env HOST/PORT
          // for LAN dev, and finally to localhost:8559 as a last resort.
          let hubBase: string;
          const _orochiUrl = process.env.SCITEX_OROCHI_URL || "";
          if (_orochiUrl) {
            try {
              const u = new URL(_orochiUrl);
              const scheme = u.protocol === "wss:" ? "https:" : "http:";
              hubBase = `${scheme}//${u.host}`;
            } catch {
              hubBase = `http://${process.env.SCITEX_OROCHI_HOST || "localhost"}:${process.env.SCITEX_OROCHI_PORT || "8559"}`;
            }
          } else {
            hubBase = `http://${process.env.SCITEX_OROCHI_HOST || "localhost"}:${process.env.SCITEX_OROCHI_PORT || "8559"}`;
          }
          const attachments: Array<{ url: string; filename: string }> = [];
          for (const a of rawAttachments as unknown[]) {
            try {
              if (a == null || typeof a !== "object") continue;
              const att = a as Record<string, unknown>;
              const u = typeof att.url === "string" ? att.url : "";
              if (!u) continue; // skip attachments with no url
              const abs = u.startsWith("http")
                ? u
                : hubBase.replace(/\/$/, "") + u;
              const filename =
                typeof att.filename === "string" ? att.filename : "file";
              attachments.push({ url: abs, filename });
            } catch (attErr) {
              _dbg(`skipping malformed attachment: ${attErr}`);
            }
          }
          if (attachments.length > 0) {
            // Cap attachment list to avoid oversized notifications
            const shown = attachments.slice(0, 10);
            const extra =
              attachments.length > 10
                ? ` (+${attachments.length - 10} more)`
                : "";
            attachmentInfo = `\n[Attachments: ${shown
              .map((a) => `${a.filename} -> ${a.url}`)
              .join(", ")}${extra}]`;
          }
        } catch (attNormErr) {
          _dbg(`attachment normalization failed: ${attNormErr}`);
        }

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
      if (_heartbeatInterval) {
        clearInterval(_heartbeatInterval);
        _heartbeatInterval = null;
      }
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
  if (name === "subscribe") return handleSubscribe(conn as any, args as any);
  if (name === "unsubscribe")
    return handleUnsubscribe(conn as any, args as any);
  if (name === "download_media") return handleDownloadMedia(args as any);
  if (name === "upload_media") return handleUploadMedia(args as any);
  if (name === "rsync_media") return handleRsyncMedia(args as any);
  if (name === "rsync_status") return handleRsyncStatus(args as any);
  if (name === "sidecar_status") return handleSidecarStatus();
  if (name === "connectivity_matrix") return handleConnectivityMatrix();
  if (name === "self_command") return handleSelfCommand(args as any);
  if (name === "dm_list") return handleDmList(args as any);
  if (name === "dm_open") return handleDmOpen(args as any);
  if (name === "export_channel") return handleExportChannel(args as any);
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
