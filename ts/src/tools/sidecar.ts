/**
 * Fleet observability tools: connectivity_matrix, sidecar_status.
 *
 * connectivity_matrix — fleet 4×4 reachability matrix (todo#297 layer 3).
 *   Reads connectivity rows produced by the per-host fleet-watch producers
 *   (PR B, e.g. NAS `scripts/fleet-watch/fleet_watch.sh emit_connectivity_row`)
 *   and returns the merged matrix as JSON. This tool deliberately does NOT
 *   call ssh or measure RTT itself — that is PR B's job.
 *
 * sidecar_status — Orochi-side sidecar PID visibility (todo#287 Slice A).
 *   Returns mcp_server PID + outstanding rsync_media jobs. The orochi half
 *   of the 3-layer PID model agreed in msg#8120.
 */
import { readFileSync, existsSync } from "fs";
import { join as pathJoin } from "path";
import { OROCHI_AGENT, MCP_SERVER_STARTED_AT } from "./_shared.js";
import { rsyncJobs } from "./rsync.js";

function connectivityCacheDir(): string {
  const override = process.env.SCITEX_OROCHI_CONNECTIVITY_DIR;
  if (override && override.trim()) return override.trim();
  const home = process.env.HOME || "";
  return pathJoin(home, ".scitex", "orochi", "fleet-watch");
}

interface ConnectivityRow {
  ts?: string;
  from?: string;
  from_hostname?: string;
  to?: Record<string, unknown>;
  [key: string]: unknown;
}

export async function handleConnectivityMatrix(): Promise<{
  content: Array<{ type: string; text: string }>;
}> {
  const dir = connectivityCacheDir();
  const rows: Record<string, ConnectivityRow> = {};
  const errors: string[] = [];
  const sources: string[] = [];

  let entries: string[] = [];
  try {
    if (existsSync(dir)) {
      const { readdirSync } = await import("fs");
      entries = readdirSync(dir);
    }
  } catch (err) {
    errors.push(`readdir: ${(err as Error).message}`);
  }

  // Match: connectivity.json (single legacy row) and connectivity-<host>.json
  const targets = entries.filter(
    (n) =>
      n === "connectivity.json" ||
      /^connectivity-[A-Za-z0-9._-]+\.json$/.test(n),
  );

  for (const name of targets) {
    const fpath = pathJoin(dir, name);
    try {
      const txt = readFileSync(fpath, "utf-8");
      const parsed = JSON.parse(txt) as ConnectivityRow;
      const fromKey =
        (parsed.from || "").trim() ||
        name.replace(/^connectivity-?/, "").replace(/\.json$/, "") ||
        "unknown";
      // Last writer per `from` wins — usually fine since each host owns its row.
      rows[fromKey] = parsed;
      sources.push(name);
    } catch (err) {
      errors.push(`${name}: ${(err as Error).message}`);
    }
  }

  const payload = {
    ts: new Date().toISOString(),
    matrix: rows,
    sources,
    errors,
    cache_dir: dir,
  };

  return {
    content: [
      {
        type: "text",
        text: JSON.stringify(payload),
      },
    ],
  };
}

export async function handleSidecarStatus(): Promise<{
  content: Array<{ type: string; text: string }>;
}> {
  const startedMs = Date.parse(MCP_SERVER_STARTED_AT);
  const uptimeSeconds = Number.isFinite(startedMs)
    ? Math.max(0, Math.round((Date.now() - startedMs) / 1000))
    : null;

  // Active rsync jobs: surface running ones first, then recently-finished
  // (status != "running") for diagnostic context. We don't filter the map —
  // callers can post-filter on `status` if they only care about live procs.
  const rsyncJobsList = Array.from(rsyncJobs.values()).map((j) => ({
    id: j.id,
    pid: j.pid ?? null,
    status: j.status,
    src_path: j.src_path,
    dst_host: j.dst_host,
    dst_path: j.dst_path,
    channel: j.channel,
    started_at: j.started_at,
    finished_at: j.finished_at ?? null,
    exit_code: j.exit_code ?? null,
  }));

  const payload = {
    ts: new Date().toISOString(),
    mcp_server: {
      agent: OROCHI_AGENT || null,
      pid: process.pid,
      ppid: typeof process.ppid === "number" ? process.ppid : null,
      started_at: MCP_SERVER_STARTED_AT,
      uptime_seconds: uptimeSeconds,
      runtime: typeof Bun !== "undefined" ? "bun" : "node",
    },
    sidecars: {
      rsync_jobs: rsyncJobsList,
    },
  };

  return {
    content: [
      {
        type: "text",
        text: JSON.stringify(payload),
      },
    ],
  };
}
