/**
 * rsync_media / rsync_status: background file transfer over SSH mesh.
 *
 * Each job:
 *  - spawns `rsync -avP --partial -e ssh <src> <dst_host>:<dst_path>` detached
 *  - streams stdout+stderr to /tmp/orochi-rsync/<job_id>.log
 *  - posts a completion or failure notice to the requested Orochi channel
 *
 * Exports `rsyncJobs` so sidecar_status can surface live PIDs.
 */
import { readFileSync, mkdirSync, existsSync, createWriteStream } from "fs";
import { basename, join as pathJoin } from "path";
import { spawn } from "child_process";
import { randomBytes } from "crypto";
import { OROCHI_AGENT, httpBase, buildFetchHeaders } from "./_shared.js";

export interface RsyncJob {
  id: string;
  src_path: string;
  dst_host: string;
  dst_path: string;
  channel: string;
  status: "running" | "done" | "failed";
  pid?: number;
  started_at: string;
  finished_at?: string;
  exit_code?: number;
  last_line?: string;
}

const RSYNC_JOB_DIR = "/tmp/orochi-rsync";
export const rsyncJobs = new Map<string, RsyncJob>();

function makeJobId(): string {
  return `rsync-${Date.now()}-${randomBytes(2).toString("hex")}`;
}

function rsyncLogPath(jobId: string): string {
  return pathJoin(RSYNC_JOB_DIR, `${jobId}.log`);
}

// Read last N non-empty lines from a log file
function tailLog(logPath: string, n = 3): string {
  try {
    const text = readFileSync(logPath, "utf-8");
    const lines = text.split("\n").filter((l) => l.trim());
    return lines.slice(-n).join("\n");
  } catch {
    return "";
  }
}

export async function handleRsyncMedia(args: {
  src_path: string;
  dst_host: string;
  dst_path: string;
  channel?: string;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  const { src_path, dst_host, dst_path } = args;
  const channel = args.channel || "#agent";

  // Validate allowed hosts (prevent shell injection via dst_host)
  const ALLOWED_HOSTS = new Set(["mba", "nas", "ywata-note-win", "spartan"]);
  if (!ALLOWED_HOSTS.has(dst_host)) {
    return {
      content: [
        {
          type: "text",
          text: `Error: dst_host must be one of: ${[...ALLOWED_HOSTS].join(", ")}`,
        },
      ],
    };
  }

  // Validate src_path exists locally
  if (!existsSync(src_path)) {
    return {
      content: [
        { type: "text", text: `Error: src_path not found: ${src_path}` },
      ],
    };
  }

  // Ensure log dir
  try {
    mkdirSync(RSYNC_JOB_DIR, { recursive: true });
  } catch {}

  const jobId = makeJobId();
  const logPath = rsyncLogPath(jobId);

  const job: RsyncJob = {
    id: jobId,
    src_path,
    dst_host,
    dst_path,
    channel,
    status: "running",
    started_at: new Date().toISOString(),
  };
  rsyncJobs.set(jobId, job);

  // Spawn rsync detached so it outlives any timeout
  const logStream = createWriteStream(logPath, { flags: "a" });

  // rsync -avP: archive, verbose, partial/progress
  // --partial: keep partial files for resume
  const child = spawn(
    "rsync",
    ["-avP", "--partial", "-e", "ssh", src_path, `${dst_host}:${dst_path}`],
    {
      detached: false,
      stdio: ["ignore", "pipe", "pipe"],
    },
  );

  job.pid = child.pid;
  logStream.write(`[rsync_media] job=${jobId} pid=${child.pid}\n`);
  logStream.write(
    `[rsync_media] cmd: rsync -avP --partial -e ssh ${src_path} ${dst_host}:${dst_path}\n`,
  );
  logStream.write(`[rsync_media] started: ${job.started_at}\n\n`);

  child.stdout?.pipe(logStream, { end: false });
  child.stderr?.pipe(logStream, { end: false });

  child.on("close", async (code) => {
    job.exit_code = code ?? -1;
    job.status = code === 0 ? "done" : "failed";
    job.finished_at = new Date().toISOString();
    job.last_line = tailLog(logPath, 5);
    logStream.write(
      `\n[rsync_media] finished: exit_code=${code} at ${job.finished_at}\n`,
    );
    logStream.end();

    // Post completion notice via HTTP API (avoid WS dependency in callback)
    const status_emoji = code === 0 ? "✅" : "❌";
    const msg =
      code === 0
        ? `${status_emoji} rsync done: \`${basename(src_path)}\` → ${dst_host}:${dst_path} (job=${jobId})`
        : `${status_emoji} rsync FAILED (exit=${code}): \`${basename(src_path)}\` → ${dst_host}:${dst_path} (job=${jobId})\n\`\`\`\n${job.last_line}\n\`\`\``;

    try {
      const tokenParamLocal = process.env.SCITEX_OROCHI_TOKEN
        ? `?token=${process.env.SCITEX_OROCHI_TOKEN}`
        : "";
      await fetch(`${httpBase}/api/messages/${tokenParamLocal}`, {
        method: "POST",
        headers: buildFetchHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          channel,
          text: msg,
          sender: OROCHI_AGENT,
        }),
      });
    } catch (err) {
      logStream.write(
        `[rsync_media] completion notify failed: ${(err as Error).message}\n`,
      );
    }
  });

  return {
    content: [
      {
        type: "text",
        text: JSON.stringify({
          job_id: jobId,
          status: "running",
          pid: job.pid,
          log: logPath,
          cmd: `rsync -avP --partial -e ssh ${src_path} ${dst_host}:${dst_path}`,
        }),
      },
    ],
  };
}

export async function handleRsyncStatus(args: {
  job_id: string;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  const job = rsyncJobs.get(args.job_id);
  if (!job) {
    return {
      content: [{ type: "text", text: `Error: job not found: ${args.job_id}` }],
    };
  }
  const logPath = rsyncLogPath(job.id);
  const tail = tailLog(logPath, 10);
  return {
    content: [
      {
        type: "text",
        text: JSON.stringify({
          job_id: job.id,
          status: job.status,
          src_path: job.src_path,
          dst_host: job.dst_host,
          dst_path: job.dst_path,
          pid: job.pid,
          started_at: job.started_at,
          finished_at: job.finished_at ?? null,
          exit_code: job.exit_code ?? null,
          log_tail: tail,
        }),
      },
    ],
  };
}
