/**
 * WebSocket connection manager with reconnect, ping/pong, and state tracking.
 */
import WebSocket from "ws";
import { orochi_hostname } from "os";
import { execSync } from "child_process";
import { OROCHI_AGENT, OROCHI_MODEL, buildWsUrl, maskUrl } from "./config.js";
import { getSystemMetrics } from "./orochi_metrics.js";

// todo#55: canonical FQDN for display next to the short orochi_machine label
// ("spartan (spartan.hpc.unimelb.edu.au)"). os.orochi_hostname() in Node returns
// the SHORT orochi_hostname on every platform we care about, so shell out to
// `orochi_hostname -f` once per process and cache. Falls back to the short
// label on hosts with no reverse DNS so the UI degrades gracefully.
let _canonicalHostname: string | null = null;
function canonicalHostname(): string {
  if (_canonicalHostname !== null) return _canonicalHostname;
  try {
    _canonicalHostname = execSync("orochi_hostname -f", {
      stdio: ["ignore", "pipe", "ignore"],
      timeout: 1_500,
    })
      .toString()
      .trim();
  } catch {
    _canonicalHostname = orochi_hostname();
  }
  return _canonicalHostname;
}

// ---------------------------------------------------------------------------
// Connection state
// ---------------------------------------------------------------------------
export type ConnectionState =
  | "disconnected"
  | "connecting"
  | "connected"
  | "reconnecting";

const PING_INTERVAL_MS = 25_000;
const PONG_TIMEOUT_MS = 10_000;
const MAX_RECONNECT_DELAY = 60_000;
const CONNECT_TIMEOUT_MS = 15_000;
const HEARTBEAT_INTERVAL_MS = 30_000;

export class OrochiConnection {
  state: ConnectionState = "disconnected";
  lastConnectedAt: Date | null = null;
  totalReconnects = 0;
  reconnectAttempts = 0;

  private ws: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private pongTimeoutTimer: ReturnType<typeof setTimeout> | null = null;
  private lastPongAt = 0;
  private isReconnecting = false;
  private onMessage: ((data: string) => void) | null = null;

  constructor(onMessage: (data: string) => void) {
    this.onMessage = onMessage;
  }

  get socket(): WebSocket | null {
    return this.ws;
  }

  get isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  get lastPongAgeMs(): number | null {
    return this.lastPongAt ? Date.now() - this.lastPongAt : null;
  }

  send(data: string): boolean {
    if (!this.isConnected) return false;
    try {
      this.ws!.send(data);
      return true;
    } catch (_) {
      return false;
    }
  }

  connect(): void {
    this.clearReconnectTimer();
    this.isReconnecting = false;
    this.setState("connecting");

    const wsUrl = buildWsUrl();
    const wsOptions: WebSocket.ClientOptions = {};
    if (
      wsUrl.startsWith("wss://") &&
      process.env.SCITEX_OROCHI_SKIP_TLS_VERIFY === "1"
    ) {
      wsOptions.rejectUnauthorized = false;
    }

    try {
      this.ws = new WebSocket(wsUrl, wsOptions);
    } catch (err) {
      console.error("[orochi] failed to create WebSocket:", err);
      this.setState("disconnected");
      this.scheduleReconnect();
      return;
    }

    const connectTimeout = setTimeout(() => {
      if (this.ws && this.ws.readyState === WebSocket.CONNECTING) {
        console.error("[orochi] connection timeout after 15s");
        this.cleanup();
        this.setState("disconnected");
        this.scheduleReconnect();
      }
    }, CONNECT_TIMEOUT_MS);

    this.ws.on("open", () => {
      clearTimeout(connectTimeout);
      this.setState("connected");
      this.lastConnectedAt = new Date();
      this.reconnectAttempts = 0;
      console.error(
        `[orochi] connected to ${maskUrl(wsUrl)} as ${OROCHI_AGENT}`,
      );
      this.register();
      this.startPingPong();
      this.startHeartbeat();
    });

    this.ws.on("pong", () => {
      this.lastPongAt = Date.now();
      if (this.pongTimeoutTimer) {
        clearTimeout(this.pongTimeoutTimer);
        this.pongTimeoutTimer = null;
      }
    });

    this.ws.on("message", (data: Buffer) => {
      this.onMessage?.(data.toString());
    });

    this.ws.on("close", (code: number, reason: Buffer) => {
      clearTimeout(connectTimeout);
      const reasonStr = reason?.toString() || "unknown";
      console.error(
        `[orochi] disconnected (code=${code}, reason=${reasonStr})`,
      );
      this.cleanup();
      this.setState("disconnected");
      this.triggerReconnect();
    });

    this.ws.on("error", (err) => {
      clearTimeout(connectTimeout);
      console.error("[orochi] websocket error:", err.message);
      this.cleanup();
      this.setState("disconnected");
      this.triggerReconnect();
    });
  }

  // -- Private helpers --

  private setState(state: ConnectionState): void {
    const prev = this.state;
    this.state = state;
    if (prev !== state) {
      console.error(`[orochi] state: ${prev} -> ${state}`);
    }
  }

  private register(): void {
    this.send(
      JSON.stringify({
        type: "register",
        sender: OROCHI_AGENT,
        payload: {
          orochi_machine: orochi_hostname(),
          // todo#55: canonical FQDN for display next to the short label.
          orochi_hostname_canonical: canonicalHostname(),
          role: "claude-code",
          orochi_model: OROCHI_MODEL,
          agent_id: `${OROCHI_AGENT}@${orochi_hostname()}`,
          orochi_project: "",
          orochi_workdir: process.cwd(),
        },
      }),
    );
  }

  private startHeartbeat(): void {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = setInterval(() => {
      if (!this.isConnected) return;
      this.send(
        JSON.stringify({
          type: "heartbeat",
          sender: OROCHI_AGENT,
          payload: getSystemMetrics(),
        }),
      );
    }, HEARTBEAT_INTERVAL_MS);
  }

  private startPingPong(): void {
    this.stopPingPong();
    this.lastPongAt = Date.now();
    this.pingTimer = setInterval(() => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
      try {
        this.ws.ping();
      } catch (_) {
        return;
      }
      if (this.pongTimeoutTimer) clearTimeout(this.pongTimeoutTimer);
      this.pongTimeoutTimer = setTimeout(() => {
        console.error("[orochi] pong timeout, closing stale connection");
        try {
          this.ws?.terminate();
        } catch (_) {}
      }, PONG_TIMEOUT_MS);
    }, PING_INTERVAL_MS);
  }

  private stopPingPong(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
    if (this.pongTimeoutTimer) {
      clearTimeout(this.pongTimeoutTimer);
      this.pongTimeoutTimer = null;
    }
  }

  private cleanup(): void {
    this.stopPingPong();
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    if (this.ws) {
      this.ws.removeAllListeners();
      try {
        this.ws.close();
      } catch (_) {}
      this.ws = null;
    }
  }

  private triggerReconnect(): void {
    if (!this.isReconnecting) {
      this.isReconnecting = true;
      this.scheduleReconnect();
    }
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    this.setState("reconnecting");
    const baseDelay = Math.min(
      2000 * Math.pow(2, this.reconnectAttempts),
      MAX_RECONNECT_DELAY,
    );
    const jitter = Math.random() * baseDelay * 0.3;
    const delay = Math.round(baseDelay + jitter);
    this.reconnectAttempts++;
    this.totalReconnects++;
    if (this.reconnectAttempts % 10 === 0) {
      console.error(
        `[orochi] reconnect attempt ${this.reconnectAttempts} (total: ${this.totalReconnects}, last: ${this.lastConnectedAt?.toISOString() || "never"})`,
      );
    } else {
      console.error(
        `[orochi] reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})...`,
      );
    }
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.isReconnecting = false;
      this.connect();
    }, delay);
  }
}
