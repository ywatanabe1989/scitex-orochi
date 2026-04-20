/**
 * Boot-time environment guards for the Orochi MCP sidecar.
 *
 * Calling `applyBootGuards()` may exit the process if the env says so —
 * it is intentionally side-effectful and must run before any WS / MCP
 * connection is attempted.
 */

// Unified truthy check for env var guards
const TRUTHY = new Set(["true", "1", "yes", "enable", "enabled"]);

export function isTruthy(val?: string): boolean {
  return TRUTHY.has((val || "").toLowerCase());
}

export function applyBootGuards(): void {
  // Generic disable switch
  if (isTruthy(process.env.SCITEX_OROCHI_DISABLE)) {
    console.error("[scitex-orochi] Disabled via SCITEX_OROCHI_DISABLE");
    process.exit(0);
  }

  // Zero-trust: telegram agents must never run this MCP server
  if (
    (process.env.SCITEX_OROCHI_AGENT_ROLE || "").toLowerCase() === "telegram"
  ) {
    console.error(
      "[scitex-orochi] BLOCKED: telegram agent must not run Orochi MCP channel",
    );
    process.exit(1);
  }

  // Safety: block if Telegram bot token env vars are present (indicates a
  // Telegram agent session). Exception: if SCITEX_OROCHI_TOKEN is explicitly
  // set, this MCP server was intentionally configured (e.g., via
  // agent-container) and should run despite telegram vars leaking from the
  // parent environment.
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
}

// Shared debug log helper — append-only so it never throws on close.
import { appendFileSync } from "fs";
export const dbg = (s: string): void => {
  try {
    appendFileSync("/tmp/orochi-mcp-debug.log", s + "\n");
  } catch {}
};
