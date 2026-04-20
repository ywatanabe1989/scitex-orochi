/**
 * Shared helpers, constants, and types used across tool modules.
 */
import {
  OROCHI_AGENT,
  OROCHI_TOKEN,
  buildHttpBase,
  buildFetchHeaders,
  buildWsUrl,
  maskUrl,
} from "../config.js";

// Lightweight interface — avoids importing connection.ts which pulls in
// metrics.ts + execSync, interfering with MCP stdio notifications.
export interface ConnLike {
  send(data: string): void;
  isConnected: boolean;
  state: string;
  lastConnectedAt: number | null;
}

export const httpBase = buildHttpBase();

export {
  OROCHI_AGENT,
  OROCHI_TOKEN,
  buildHttpBase,
  buildFetchHeaders,
  buildWsUrl,
  maskUrl,
};

export function tokenParam(prefix: "?" | "&"): string {
  return OROCHI_TOKEN ? `${prefix}token=${OROCHI_TOKEN}` : "";
}

export const MIME: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  gif: "image/gif",
  webp: "image/webp",
  svg: "image/svg+xml",
  pdf: "application/pdf",
  txt: "text/plain",
  md: "text/markdown",
  json: "application/json",
  csv: "text/csv",
};

export function normalizeGroupChannel(name: string): string {
  const trimmed = (name || "").trim();
  if (!trimmed) return "";
  if (trimmed.startsWith("dm:") || trimmed.startsWith("#")) return trimmed;
  return `#${trimmed}`;
}

export function resolveWorkspaceSlug(arg?: string): string | null {
  return (arg || process.env.SCITEX_OROCHI_WORKSPACE || "").trim() || null;
}

// MCP server (this bun process) start time for sidecar_status / uptime.
// Captured at module load.
export const MCP_SERVER_STARTED_AT = new Date().toISOString();
