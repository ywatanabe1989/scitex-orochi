/**
 * Direct WebSocket connection (replaces OrochiConnection class).
 * The class wrapper was suspected of interfering with idle-state
 * MCP notifications -- this minimal approach mirrors the working
 * /tmp/test-channel-ws.ts pattern.
 */
import WebSocket from "ws";
import type { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { homedir } from "os";
import { readFileSync, existsSync } from "fs";
import { join } from "path";
import {
  OROCHI_AGENT,
  OROCHI_MODEL,
  buildWsUrl,
  maskUrl,
} from "../src/config.js";
import { dbg } from "./guards.js";
import { pushRegistryHeartbeat } from "./heartbeat.js";
import { handleWsMessage } from "./dispatch.js";
import { resolveHostLabel } from "./hostname.js";

let _ws: WebSocket | null = null;
let _heartbeatInterval: ReturnType<typeof setInterval> | null = null;
let _mcpRef: Server | null = null;

// Lightweight adapter that satisfies the OrochiConnection interface
// expected by tools.ts (isConnected, state, send, reconnectAttempts, etc.)
export const conn = {
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
    dbg(`ws connecting to ${maskUrl(wsUrl)}`);
    conn.state = "connecting";

    _ws = new WebSocket(wsUrl);

    _ws.on("open", () => onOpen(_ws!));
    _ws.on("message", (data: Buffer) => {
      if (!_mcpRef || !_ws) return;
      handleWsMessage(_mcpRef, _ws, data);
    });
    _ws.on("close", (code: number, reason: Buffer) => onClose(code, reason));
    _ws.on("error", (err) => {
      console.error("[orochi] ws error:", err.message);
      dbg(`ws error: ${err.message}`);
      // close event will fire after error, triggering reconnect
    });
  },
};

export function attachMcp(mcp: Server): void {
  _mcpRef = mcp;
}

function onOpen(ws: WebSocket): void {
  conn.state = "connected";
  conn.lastConnectedAt = new Date();
  conn.reconnectAttempts = 0;
  console.error(`[orochi] ws connected as ${OROCHI_AGENT}`);
  dbg(`ws open`);

  startAppHeartbeat(ws);
  startRegistryHeartbeat();

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

  // Register with the hub.
  //
  // Host identity source order (post-PR#309 / post-ywatanabe msg#16102):
  //   1. Live ``hostname()`` mapped through
  //      ``spec.hostname_aliases`` in
  //      ``~/.scitex/orochi/shared/config.yaml`` — so
  //      ``Yusukes-MacBook-Air`` → ``mba``,
  //      ``DXP480TPLUS-994`` → ``nas``, etc.
  //   2. Raw short ``hostname()`` when no alias entry matches.
  //   3. Env fallback (``SCITEX_OROCHI_MACHINE`` /
  //      ``SCITEX_OROCHI_HOSTNAME`` /
  //      ``SCITEX_AGENT_CONTAINER_HOSTNAME``) — only when
  //      ``hostname()`` returns empty (stripped container).
  //
  // PR#309 flipped env/hostname priority (root fix for lead
  // msg#15578 — stale ``SCITEX_OROCHI_HOSTNAME=mba`` inherited into
  // a spartan process) but skipped the alias map on the TS side,
  // which caused the ``Yusukes-MacBook-Air`` regression (ywatanabe
  // msg#16102). Alias application restored here so the hub sees the
  // canonical fleet short name.
  const _machine = resolveHostLabel();
  const _liveHostname = _machine;
  ws.send(
    JSON.stringify({
      type: "register",
      sender: OROCHI_AGENT,
      payload: {
        machine: _machine,
        // Live hostname(1) surfaced separately from ``machine`` so the
        // hub / frontend can render the authoritative ``<name>@<host>``
        // badge directly from the kernel's answer, bypassing any
        // env-var-driven ``machine`` override.
        hostname: _liveHostname,
        role: process.env.SCITEX_OROCHI_ROLE || "claude-code",
        model: OROCHI_MODEL,
        multiplexer: process.env.SCITEX_OROCHI_MULTIPLEXER || "tmux",
        agent_id: `${OROCHI_AGENT}@${_machine}`,
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
}

// App-level heartbeat + liveness alarm.
// Daphne does NOT respond to WebSocket protocol-level ping frames,
// so we do NOT terminate on missing pong. Instead, if the connection
// seems dead (send fails), we emit an alarm for healers.
function startAppHeartbeat(ws: WebSocket): void {
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
        dbg(`alarm: hub unreachable ${silentMs}ms`);
        // Notify Claude Code so it can post to #escalation
        try {
          _mcpRef?.notification({
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
  ws.on("close", () => clearInterval(_pingInterval));
}

// Registry heartbeat — fire immediately, then every 30s while connected.
// Stopped in the ws close handler.
function startRegistryHeartbeat(): void {
  if (_heartbeatInterval) {
    clearInterval(_heartbeatInterval);
    _heartbeatInterval = null;
  }
  pushRegistryHeartbeat().catch(() => {});
  _heartbeatInterval = setInterval(() => {
    pushRegistryHeartbeat().catch(() => {});
  }, 30000);
}

function onClose(code: number, reason: Buffer): void {
  const reasonStr = reason?.toString() || "unknown";
  console.error(`[orochi] ws disconnected (code=${code}, reason=${reasonStr})`);
  dbg(`ws close code=${code}`);
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
}
