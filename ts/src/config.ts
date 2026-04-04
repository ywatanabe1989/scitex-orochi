/**
 * Orochi push client configuration -- environment-based settings.
 */
import { hostname } from "os";

export const OROCHI_HOST = process.env.OROCHI_HOST || "192.168.0.102";
export const OROCHI_PORT = parseInt(process.env.OROCHI_PORT || "8559");
export const OROCHI_AGENT = process.env.OROCHI_AGENT || `${hostname()}-claude`;
export const OROCHI_CHANNELS = (process.env.OROCHI_CHANNELS || "#general")
  .split(",")
  .map((s) => s.trim());
export const OROCHI_TOKEN = process.env.OROCHI_TOKEN || "";
export const OROCHI_MODEL = process.env.OROCHI_MODEL || "unknown";

// WSS support: OROCHI_URL overrides host/port with a full URL (ws:// or wss://)
// This enables connections through Cloudflare tunnels (issue #80).
// Examples:
//   OROCHI_URL=wss://orochi.scitex.ai      (Cloudflare tunnel)
//   OROCHI_URL=ws://192.168.0.102:9559      (direct LAN)
export const OROCHI_URL = process.env.OROCHI_URL || "";

export function buildWsUrl(): string {
  if (OROCHI_URL) {
    // Full URL override — append /ws/agent/ path and token
    const base = OROCHI_URL.replace(/\/$/, "");
    const path = base.includes("/ws/agent") ? "" : "/ws/agent/";
    const sep = base.includes("?") ? "&" : "?";
    return OROCHI_TOKEN
      ? `${base}${path}${sep}token=${OROCHI_TOKEN}&agent=${OROCHI_AGENT}`
      : `${base}${path}`;
  }
  const tokenParam = OROCHI_TOKEN
    ? `token=${OROCHI_TOKEN}&agent=${OROCHI_AGENT}`
    : `agent=${OROCHI_AGENT}`;
  return `ws://${OROCHI_HOST}:${OROCHI_PORT}/ws/agent/?${tokenParam}`;
}

export function buildHttpBase(): string {
  if (OROCHI_URL) {
    // Derive HTTP URL from WS URL: wss:// -> https://, ws:// -> http://
    // Django serves both HTTP and WS on the same port via ASGI
    return OROCHI_URL.replace(/^wss:\/\//, "https://").replace(
      /^ws:\/\//,
      "http://",
    );
  }
  // Django ASGI: same port for HTTP and WS
  return `http://${OROCHI_HOST}:${OROCHI_PORT}`;
}

/** Mask token in URLs for safe logging. */
export function maskUrl(url: string): string {
  return url.replace(/token=[^&]+/, "token=***");
}
