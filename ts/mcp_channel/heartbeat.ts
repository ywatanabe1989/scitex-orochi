/**
 * Registry heartbeat — thin pump.
 *
 * The sidecar shells out to
 *     ~/.scitex/orochi/scripts/collect_agent_metadata.py <agent>
 * which reads the live Claude Code session jsonl transcript and emits
 * claude-hud-style metadata (alive, subagents, orochi_context_pct, current_tool,
 * last_activity, model, ...) as a single JSON line. The resulting dict is
 * spread into the hub heartbeat payload.
 *
 * Historical note: this used to call `scitex-agent-container status
 * <agent> --json` instead, but most fleet agents are launched directly via
 * tmux + raw `claude` (not via `scitex-agent-container start`), so they are
 * invisible to scitex-agent-container's own registry. The status command
 * returned `{"error": "Agent X not found in registry"}` with rc=1 for every
 * such agent, the spawn was treated as a hard failure, and pushRegistryHeartbeat
 * returned without ever populating the hub's current_task / subagents /
 * orochi_context_pct fields. The Activity tab then rendered "no task / 0 subs / no
 * ctx" for everyone — exactly the symptom ywatanabe flagged at msg#6382. The
 * collect_agent_metadata.py path bypasses the broken registry lookup entirely (todo#155).
 */
import { spawnSync } from "child_process";
import { hostname, homedir } from "os";
import { existsSync } from "fs";
import { join } from "path";
import {
  OROCHI_AGENT,
  OROCHI_TOKEN,
  buildHttpBase,
  maskUrl,
} from "../src/config.js";
import { dbg } from "./guards.js";

export async function pushRegistryHeartbeat(): Promise<void> {
  if (process.env.SCITEX_OROCHI_REGISTRY_DISABLE === "1") return;
  if (!OROCHI_TOKEN) {
    dbg("heartbeat: no OROCHI_TOKEN, skipping");
    return;
  }
  const agentMetaPath = join(
    homedir(),
    ".scitex",
    "orochi",
    "scripts",
    "collect_agent_metadata.py",
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
        `[orochi-heartbeat] collect_agent_metadata.py failed: ${(result.stderr || "").slice(0, 200)}`,
      );
      dbg(`heartbeat: agent_meta rc=${result.status}`);
      return;
    }
    meta = JSON.parse(result.stdout);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[orochi-heartbeat] agent_meta spawn failed: ${msg}`);
    dbg(`heartbeat: spawn err ${msg}`);
    return;
  }

  // collect_agent_metadata.py field names → hub /api/agents/register field names.
  // The hub renderer (activity-tab.js) reads `current_task`,
  // `subagent_count`, `orochi_context_pct`, `model`. collect_agent_metadata.py emits
  // `current_tool`, `subagents`, `orochi_context_pct`, `model`. Translate.
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
    // Host identity: trust live ``hostname()`` first, fall back to env
    // only when the kernel returns empty (stripped container). Env-
    // first was the root cause of lead msg#15578 (proj-neurovista
    // misreporting as mba) — a stale SCITEX_OROCHI_HOSTNAME env var
    // inherited into a spartan process would override the real host.
    machine:
      hostname() ||
      process.env.SCITEX_OROCHI_MACHINE ||
      process.env.SCITEX_OROCHI_HOSTNAME ||
      process.env.SCITEX_AGENT_CONTAINER_HOSTNAME ||
      "",
    // Live hostname(1) — surfaced distinctly from ``machine`` so the
    // hub / frontend can prefer this authoritative signal when deriving
    // the ``<name>@<host>`` badge. Never sourced from env.
    hostname: hostname() || "",
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
      dbg(`heartbeat failed: ${res.status} ${txt.slice(0, 200)}`);
    } else {
      dbg(`heartbeat ok: ${OROCHI_AGENT} -> ${maskUrl(url)}`);
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[orochi-heartbeat] fetch error: ${msg}`);
    dbg(`heartbeat error: ${msg}`);
  }
}
