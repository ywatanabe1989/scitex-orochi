/**
 * Orochi push client configuration -- environment-based settings.
 */
import { hostname } from "os";

export const OROCHI_HOST = process.env.OROCHI_HOST || "192.168.0.102";
export const OROCHI_PORT = parseInt(process.env.OROCHI_PORT || "9559");
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
    const sep = OROCHI_URL.includes("?") ? "&" : "?";
    return OROCHI_TOKEN
      ? `${OROCHI_URL}${sep}token=${OROCHI_TOKEN}`
      : OROCHI_URL;
  }
  return `ws://${OROCHI_HOST}:${OROCHI_PORT}${OROCHI_TOKEN ? `?token=${OROCHI_TOKEN}` : ""}`;
}

export function buildHttpBase(): string {
  if (OROCHI_URL) {
    // Derive HTTP URL from WS URL: wss:// -> https://, ws:// -> http://
    // For tunnel URLs (wss://orochi.scitex.ai) the HTTP API is on the same origin
    return OROCHI_URL.replace(/^wss:\/\//, "https://").replace(
      /^ws:\/\//,
      "http://",
    );
  }
  const httpPort = OROCHI_PORT - 1000; // 9559 -> 8559
  return `http://${OROCHI_HOST}:${httpPort}`;
}

/** Mask token in URLs for safe logging. */
export function maskUrl(url: string): string {
  return url.replace(/token=[^&]+/, "token=***");
}
