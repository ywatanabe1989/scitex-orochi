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

// ── Structured error envelope (issue #262 §9.2) ──────────────────────────
//
// Every MCP tool returns either a content text payload OR a structured
// error envelope ``{ "error": { code, reason, hint } }`` packed as the
// ``text`` of a single content block. Centralizing the codes + helper
// here means callers (LLM-side or programmatic) can machine-parse the
// failure mode without scraping ``Error: HTTP 404 — <html>`` strings.

/** Closed enum of error codes a tool may surface. */
export const MCP_ERROR_CODES = {
  /** Tool requires the target agent to have a live MCP sidecar, but it does not. */
  AGENT_OFFLINE: "agent_offline",
  /** Caller is not a member of the workspace the action targets. */
  NOT_WORKSPACE_MEMBER: "not_workspace_member",
  /** Caller authenticated, but lacks the admin/staff role required. */
  PERMISSION_DENIED: "permission_denied",
  /** Caller-supplied argument is missing or malformed. */
  INVALID_INPUT: "invalid_input",
  /** Resource (channel, agent, message, ...) does not exist. */
  NOT_FOUND: "not_found",
  /** Anything else — wraps unexpected exceptions or upstream failures. */
  INTERNAL_ERROR: "internal_error",
} as const;

export type McpErrorCode = (typeof MCP_ERROR_CODES)[keyof typeof MCP_ERROR_CODES];

export interface McpErrorPayload {
  error: { code: McpErrorCode; reason: string; hint: string };
}

/**
 * Build a structured error response for an MCP tool. Pack the JSON as the
 * ``text`` of a single content block so existing MCP clients render it
 * verbatim while machine consumers can ``JSON.parse(result.content[0].text)``
 * and key off ``result.error.code``.
 */
export function mcpError(
  code: McpErrorCode,
  reason: string,
  hint: string,
): { content: Array<{ type: string; text: string }> } {
  const payload: McpErrorPayload = { error: { code, reason, hint } };
  return { content: [{ type: "text", text: JSON.stringify(payload) }] };
}
