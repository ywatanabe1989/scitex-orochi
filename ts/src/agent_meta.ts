/**
 * Agent metadata collection for heartbeat payloads.
 *
 * Shells out to `python3 ~/.scitex/orochi/shared/scripts/agent_meta.py <agent>`
 * (with a legacy fallback to the old flat `scripts/` path during dotfiles
 * 68bd1592 rollout — DEPRECATED, remove once every host is migrated.)
 * The script introspects the local Claude Code session and returns JSON like:
 *   {
 *     "agent": "head-mba",
 *     "alive": true,
 *     "subagents": 1,
 *     "context_pct": 59.0,
 *     "current_tool": "Agent",
 *     "last_activity": "2026-04-12T05:38:04.540Z",
 *     "model": "claude-opus-4-7"
 *   }
 *
 * Design:
 *   - Non-blocking: refresh runs on its own timer via `startAgentMetaRefresh`.
 *   - Heartbeats read from an in-memory cache via `getAgentMeta()`.
 *   - If the script fails/times out, the cache falls back to zero/empty
 *     values so the heartbeat shape stays stable.
 */
import { execFile } from "child_process";
import { existsSync } from "fs";
import { homedir } from "os";
import { join } from "path";
import { OROCHI_AGENT } from "./config.js";

// Canonical path (dotfiles commit 68bd1592, Phase A restructure): agent_meta.py
// now lives under shared/scripts/. Fall back to the legacy flat path while
// hosts finish re-bootstrapping. DEPRECATED: drop legacy branch after rollout.
const _CANONICAL_SCRIPT_PATH = join(
  homedir(),
  ".scitex/orochi/shared/scripts/agent_meta.py",
);
const _LEGACY_SCRIPT_PATH = join(
  homedir(),
  ".scitex/orochi/scripts/agent_meta.py",
);
const SCRIPT_PATH = existsSync(_CANONICAL_SCRIPT_PATH)
  ? _CANONICAL_SCRIPT_PATH
  : _LEGACY_SCRIPT_PATH;
const EXEC_TIMEOUT_MS = 5_000;

export type AgentMeta = {
  subagent_count: number;
  context_usage_percent: number;
  current_task: string;
  current_tool: string;
};

const EMPTY_META: AgentMeta = {
  subagent_count: 0,
  context_usage_percent: 0,
  current_task: "",
  current_tool: "",
};

let cached: AgentMeta = { ...EMPTY_META };
let refreshTimer: ReturnType<typeof setInterval> | null = null;
let inFlight = false;

/** Most recently collected agent metadata (safe default if never refreshed). */
export function getAgentMeta(): AgentMeta {
  return cached;
}

function runAgentMetaScript(agent: string): Promise<AgentMeta> {
  return new Promise((resolve) => {
    execFile(
      "python3",
      [SCRIPT_PATH, agent],
      { timeout: EXEC_TIMEOUT_MS, windowsHide: true },
      (err, stdout, stderr) => {
        if (err) {
          console.error(
            `[orochi] agent_meta failed: ${err.message}${
              stderr ? ` (${String(stderr).trim()})` : ""
            }`,
          );
          resolve({ ...EMPTY_META });
          return;
        }
        try {
          const obj = JSON.parse(stdout);
          resolve({
            subagent_count: Number(obj.subagents ?? 0) || 0,
            context_usage_percent: Number(obj.context_pct ?? 0) || 0,
            current_task: String(obj.current_task ?? ""),
            current_tool: String(obj.current_tool ?? ""),
          });
        } catch (parseErr) {
          console.error(
            `[orochi] agent_meta parse error: ${(parseErr as Error).message}`,
          );
          resolve({ ...EMPTY_META });
        }
      },
    );
  });
}

async function refreshOnce(): Promise<void> {
  if (inFlight) return;
  if (!OROCHI_AGENT) return;
  inFlight = true;
  try {
    cached = await runAgentMetaScript(OROCHI_AGENT);
  } finally {
    inFlight = false;
  }
}

/**
 * Start periodic agent_meta refresh. Safe to call multiple times; subsequent
 * calls are no-ops. Runs an immediate refresh on startup.
 */
export function startAgentMetaRefresh(intervalMs: number): void {
  if (refreshTimer) return;
  // Fire-and-forget initial refresh so first heartbeat has data if possible.
  void refreshOnce();
  refreshTimer = setInterval(() => {
    void refreshOnce();
  }, intervalMs);
  // Don't keep the event loop alive just for this.
  if (typeof (refreshTimer as any)?.unref === "function") {
    (refreshTimer as any).unref();
  }
}

export function stopAgentMetaRefresh(): void {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
}
