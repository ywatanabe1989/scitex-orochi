/**
 * MCP tool handlers for Orochi push client: reply, history, status, context.
 */
import {
  readFileSync,
  unlinkSync,
  writeFileSync,
  mkdirSync,
  existsSync,
  createWriteStream,
} from "fs";
import { basename, dirname, join as pathJoin } from "path";
import { exec, execSync, spawn } from "child_process";
import { randomBytes, createHash } from "crypto";
import {
  OROCHI_AGENT,
  OROCHI_TOKEN,
  buildHttpBase,
  buildFetchHeaders,
  buildWsUrl,
  maskUrl,
} from "./config.js";
// Lightweight interface — avoids importing connection.ts which pulls in
// metrics.ts + execSync, interfering with MCP stdio notifications.
interface ConnLike {
  send(data: string): void;
  isConnected: boolean;
  state: string;
  lastConnectedAt: number | null;
}

const httpBase = buildHttpBase();

// MCP server (this bun process) start time for sidecar_status / uptime.
// Captured at module load.
const MCP_SERVER_STARTED_AT = new Date().toISOString();

function tokenParam(prefix: "?" | "&"): string {
  return OROCHI_TOKEN ? `${prefix}token=${OROCHI_TOKEN}` : "";
}

export async function handleReply(
  conn: ConnLike,
  args: { chat_id: string; text: string; reply_to?: string; files?: string[] },
): Promise<{ content: Array<{ type: string; text: string }> }> {
  if (!conn.isConnected) {
    return {
      content: [
        {
          type: "text",
          text: `Error: not connected to Orochi (state=${conn.state}, attempts=${conn.reconnectAttempts})`,
        },
      ],
    };
  }

  const attachments: Array<Record<string, unknown>> = [];
  if (args.files && args.files.length > 0) {
    for (const filePath of args.files) {
      try {
        const fileData = readFileSync(filePath);
        const b64 = fileData.toString("base64");
        const filename = basename(filePath);
        const ext = filename.split(".").pop()?.toLowerCase() || "";
        const MIME: Record<string, string> = {
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
        const mime_type = MIME[ext] || "application/octet-stream";
        const resp = await fetch(
          `${httpBase}/api/upload-base64${tokenParam("?")}`,
          {
            method: "POST",
            headers: buildFetchHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify({ data: b64, filename, mime_type }),
          },
        );
        if (resp.ok) {
          attachments.push((await resp.json()) as Record<string, unknown>);
        } else {
          console.error(
            `[orochi] upload failed for ${filename}: HTTP ${resp.status}`,
          );
        }
      } catch (err) {
        console.error(
          `[orochi] error uploading ${filePath}:`,
          (err as Error).message,
        );
      }
    }
  }

  const metadata: Record<string, unknown> = args.reply_to
    ? { reply_to: args.reply_to }
    : {};
  if (attachments.length > 0) metadata.attachments = attachments;
  const payload: Record<string, unknown> = {
    channel: args.chat_id,
    text: args.text,
    metadata,
  };

  conn.send(JSON.stringify({ type: "message", sender: OROCHI_AGENT, payload }));
  return { content: [{ type: "text", text: "sent" }] };
}

export async function handleHistory(args: {
  channel?: string;
  limit?: number;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  // Previously this called Django's /api/messages REST endpoint, but
  // that view requires session auth (login cookie) which the MCP
  // server can't provide, so every call returned HTTP 400/302. Read
  // from the in-memory buffer instead — mcp_channel.ts populates it
  // for every message that flows through the persistent WebSocket,
  // and the WS was authenticated via the workspace token at
  // connection time.
  const { getRecentMessages } = await import("./message_buffer.js");
  const channel = args.channel || "#general";
  const limit = args.limit || 10;

  const messages = getRecentMessages(channel, limit);
  if (messages.length === 0) {
    return {
      content: [
        {
          type: "text",
          text:
            `(no messages in buffer for ${channel}) — the MCP history ` +
            "buffer only contains messages received since this agent " +
            "session started. Older messages are only visible via the " +
            "dashboard.",
        },
      ],
    };
  }

  const formatted = messages
    .map((m) => {
      let line = `[${m.ts}] ${m.sender}${m.id !== null ? ` (msg#${m.id})` : ""}: ${m.content}`;
      const attachments = (m.metadata as any)?.attachments;
      if (Array.isArray(attachments) && attachments.length > 0) {
        const refs = attachments
          .map((a: any) => `${a.filename || "file"} -> ${a.url || ""}`)
          .filter((s: string) => s.includes("->"))
          .join(", ");
        if (refs) line += `\n[Attachments: ${refs}]`;
      }
      return line;
    })
    .join("\n");

  return {
    content: [{ type: "text", text: formatted }],
  };
}

export async function handleHealth(args: {
  agent?: string;
  status?: string;
  reason?: string;
  source?: string;
  updates?: Array<{
    agent: string;
    status: string;
    reason?: string;
    source?: string;
  }>;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  try {
    const url = `${httpBase}/api/agents/health/${tokenParam("?")}`;
    const body: Record<string, unknown> = {};
    if (args.updates) body.updates = args.updates;
    else {
      if (!args.agent || !args.status) {
        return {
          content: [
            {
              type: "text",
              text: "Error: agent and status required (or pass updates[])",
            },
          ],
        };
      }
      body.agent = args.agent;
      body.status = args.status;
      if (args.reason) body.reason = args.reason;
      if (args.source) body.source = args.source;
      else body.source = OROCHI_AGENT;
    }
    const resp = await fetch(url, {
      method: "POST",
      headers: buildFetchHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const t = await resp.text();
      return {
        content: [
          {
            type: "text",
            text: `Error: HTTP ${resp.status} — ${t.slice(0, 200)}`,
          },
        ],
      };
    }
    const out = (await resp.json()) as { applied?: number };
    return {
      content: [{ type: "text", text: `health applied: ${out.applied ?? 0}` }],
    };
  } catch (err) {
    return {
      content: [{ type: "text", text: `Error: ${(err as Error).message}` }],
    };
  }
}

export async function handleTask(
  conn: ConnLike,
  args: { task: string },
): Promise<{ content: Array<{ type: string; text: string }> }> {
  if (!conn.isConnected) {
    return { content: [{ type: "text", text: "Error: not connected" }] };
  }
  const task = (args.task || "").slice(0, 200);
  conn.send(
    JSON.stringify({
      type: "task_update",
      sender: OROCHI_AGENT,
      payload: { task },
    }),
  );
  return { content: [{ type: "text", text: `task: ${task}` }] };
}

export async function handleSubagents(
  conn: ConnLike,
  args: { subagents: Array<{ name?: string; task?: string; status?: string }> },
): Promise<{ content: Array<{ type: string; text: string }> }> {
  if (!conn.isConnected) {
    return { content: [{ type: "text", text: "Error: not connected" }] };
  }
  const list = Array.isArray(args.subagents) ? args.subagents : [];
  conn.send(
    JSON.stringify({
      type: "subagents_update",
      sender: OROCHI_AGENT,
      payload: { subagents: list },
    }),
  );
  return {
    content: [{ type: "text", text: `reported ${list.length} subagent(s)` }],
  };
}

export async function handleReact(args: {
  message_id: number | string;
  emoji: string;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  const messageId = String(args.message_id);
  const emoji = args.emoji;
  if (!messageId || !emoji) {
    return {
      content: [{ type: "text", text: "Error: message_id and emoji required" }],
    };
  }
  try {
    const url = `${httpBase}/api/reactions/${tokenParam("?")}`;
    const resp = await fetch(url, {
      method: "POST",
      headers: buildFetchHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        message_id: Number(messageId),
        emoji,
        reactor: OROCHI_AGENT,
      }),
    });
    if (!resp.ok) {
      const body = await resp.text();
      return {
        content: [
          {
            type: "text",
            text: `Error: HTTP ${resp.status} — ${body.slice(0, 200)}`,
          },
        ],
      };
    }
    return {
      content: [{ type: "text", text: `reacted ${emoji} to ${messageId}` }],
    };
  } catch (err) {
    return {
      content: [{ type: "text", text: `Error: ${(err as Error).message}` }],
    };
  }
}

export async function handleContext(args: {
  screen_name?: string;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  const screenName = args.screen_name || OROCHI_AGENT;
  const tmpFile = `/tmp/screen-context-${screenName}.txt`;
  try {
    // Capture screen hardcopy
    execSync(`screen -S ${screenName} -X hardcopy ${tmpFile}`, {
      timeout: 5000,
    });
    const raw = readFileSync(tmpFile, "utf-8");
    try {
      unlinkSync(tmpFile);
    } catch {}

    // Parse context percentage from statusline.
    // claude-hud formats like "42% (2h 15m / 5h)" or just "42%"
    const lines = raw.split("\n").filter((l) => l.trim());
    // Search from bottom up — statusline is typically the last non-empty line
    let contextPercent: number | null = null;
    let rawStatusline = "";
    for (let i = lines.length - 1; i >= Math.max(0, lines.length - 5); i--) {
      const line = lines[i];
      const match = line.match(/(\d+)%/);
      if (match) {
        contextPercent = parseInt(match[1], 10);
        rawStatusline = line.trim();
        break;
      }
    }

    if (contextPercent === null) {
      return {
        content: [
          {
            type: "text",
            text: `Could not parse context percentage from screen "${screenName}". Last 3 lines:\n${lines.slice(-3).join("\n")}`,
          },
        ],
      };
    }

    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            context_percent: contextPercent,
            raw_statusline: rawStatusline,
          }),
        },
      ],
    };
  } catch (err) {
    return {
      content: [
        {
          type: "text",
          text: `Error reading screen "${screenName}": ${(err as Error).message}`,
        },
      ],
    };
  }
}

export function handleStatus(conn: ConnLike): {
  content: Array<{ type: string; text: string }>;
} {
  const uptime = conn.lastConnectedAt
    ? Math.round((Date.now() - conn.lastConnectedAt.getTime()) / 1000)
    : 0;
  return {
    content: [
      {
        type: "text",
        text: [
          `state: ${conn.state}`,
          `agent: ${OROCHI_AGENT}`,
          `url: ${maskUrl(buildWsUrl())}`,
          `connected_since: ${conn.lastConnectedAt?.toISOString() || "never"}`,
          `uptime_seconds: ${conn.state === "connected" ? uptime : 0}`,
          `reconnect_attempts: ${conn.reconnectAttempts}`,
          `total_reconnects: ${conn.totalReconnects}`,
          `last_pong_age_ms: ${conn.lastPongAgeMs ?? "n/a"}`,
        ].join("\n"),
      },
    ],
  };
}

function normalizeGroupChannel(name: string): string {
  const trimmed = (name || "").trim();
  if (!trimmed) return "";
  if (trimmed.startsWith("dm:") || trimmed.startsWith("#")) return trimmed;
  return `#${trimmed}`;
}

export async function handleSubscribe(
  conn: ConnLike,
  args: { channel: string },
): Promise<{ content: Array<{ type: string; text: string }> }> {
  const channel = normalizeGroupChannel(args.channel);
  if (!channel) {
    return { content: [{ type: "text", text: "Error: channel required" }] };
  }
  if (!conn.isConnected) {
    return {
      content: [
        { type: "text", text: `Error: not connected (state=${conn.state})` },
      ],
    };
  }
  conn.send(
    JSON.stringify({
      type: "subscribe",
      sender: OROCHI_AGENT,
      payload: { channel },
    }),
  );
  return { content: [{ type: "text", text: `subscribed: ${channel}` }] };
}

export async function handleUnsubscribe(
  conn: ConnLike,
  args: { channel: string },
): Promise<{ content: Array<{ type: string; text: string }> }> {
  const channel = normalizeGroupChannel(args.channel);
  if (!channel) {
    return { content: [{ type: "text", text: "Error: channel required" }] };
  }
  if (!conn.isConnected) {
    return {
      content: [
        { type: "text", text: `Error: not connected (state=${conn.state})` },
      ],
    };
  }
  conn.send(
    JSON.stringify({
      type: "unsubscribe",
      sender: OROCHI_AGENT,
      payload: { channel },
    }),
  );
  return { content: [{ type: "text", text: `unsubscribed: ${channel}` }] };
}

const MEDIA_DIR = "/tmp/orochi-media";

export async function handleDownloadMedia(args: {
  url: string;
  output_path?: string;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  try {
    // Resolve URL: if relative, prepend hub base
    let fullUrl = args.url;
    if (!fullUrl.startsWith("http")) {
      fullUrl =
        httpBase.replace(/\/$/, "") +
        (fullUrl.startsWith("/") ? "" : "/") +
        fullUrl;
    }

    // Append token if needed
    const sep = fullUrl.includes("?") ? "&" : "?";
    const fetchUrl = OROCHI_TOKEN
      ? `${fullUrl}${sep}token=${OROCHI_TOKEN}`
      : fullUrl;

    const resp = await fetch(fetchUrl, {
      headers: buildFetchHeaders(),
    });
    if (!resp.ok) {
      return {
        content: [
          {
            type: "text",
            text: `Error: HTTP ${resp.status} downloading ${fullUrl}`,
          },
        ],
      };
    }

    // Determine output path
    const urlPath = new URL(fullUrl).pathname;
    const filename = basename(urlPath) || "download";
    const outputPath = args.output_path || `${MEDIA_DIR}/${filename}`;

    // Ensure directory exists
    const dir = dirname(outputPath);
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true });
    }

    const buffer = Buffer.from(await resp.arrayBuffer());
    writeFileSync(outputPath, buffer);

    return {
      content: [
        {
          type: "text",
          text: `Downloaded to ${outputPath} (${buffer.length} bytes)`,
        },
      ],
    };
  } catch (err) {
    return {
      content: [{ type: "text", text: `Error: ${(err as Error).message}` }],
    };
  }
}

export async function handleUploadMedia(args: {
  file_path: string;
  channel?: string;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  try {
    if (!existsSync(args.file_path)) {
      return {
        content: [
          { type: "text", text: `Error: file not found: ${args.file_path}` },
        ],
      };
    }

    const fileData = readFileSync(args.file_path);
    const filename = basename(args.file_path);

    // --- Content-addressable dedup: check hash before uploading ---
    //
    // todo#97: a HEAD/GET on /api/media/by-hash/ confirms the blob is
    // already on the hub, but we MUST also create a Message row so the
    // file shows up in the channel feed and Files tab. Prior versions
    // returned the existing URL here without creating a Message, leaving
    // dedup-hit uploads invisible (orphaned blobs). The fix is to POST
    // back to the same endpoint with {channel, sender}; the server then
    // creates the Message row referencing the existing blob without any
    // bandwidth cost.
    const contentHash = createHash("sha256").update(fileData).digest("hex");
    const hashCheckUrl = `${httpBase}/api/media/by-hash/${contentHash}${tokenParam("?")}`;
    const targetChannel = args.channel || "#general";
    try {
      const headResp = await fetch(hashCheckUrl, {
        method: "HEAD",
        headers: buildFetchHeaders(),
      });
      if (headResp.ok) {
        // Dedup hit — POST to attach the existing blob to the target
        // channel as a Message row (no upload required).
        const attachResp = await fetch(hashCheckUrl, {
          method: "POST",
          headers: buildFetchHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({
            channel: targetChannel,
            sender: OROCHI_AGENT,
          }),
        });
        if (attachResp.ok) {
          const attached = (await attachResp.json()) as {
            url?: string;
            message_id?: number;
          };
          const mediaUrl = attached.url
            ? attached.url.startsWith("http")
              ? attached.url
              : `${httpBase}${attached.url}`
            : "unknown";
          return {
            content: [
              {
                type: "text",
                text: `Uploaded ${filename} -> ${mediaUrl} (deduplicated; attached as message ${attached.message_id ?? "?"})`,
              },
            ],
          };
        }
        // attach failed — fall through to full upload
      }
    } catch {
      // Dedup check failed — fall through to normal upload
    }

    const b64 = fileData.toString("base64");
    const ext = filename.split(".").pop()?.toLowerCase() || "";
    const MIME: Record<string, string> = {
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
    const mime_type = MIME[ext] || "application/octet-stream";

    const resp = await fetch(
      `${httpBase}/api/upload-base64${tokenParam("?")}`,
      {
        method: "POST",
        headers: buildFetchHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          data: b64,
          filename,
          mime_type,
          channel: args.channel || "#general",
          sender: OROCHI_AGENT,
        }),
      },
    );

    if (!resp.ok) {
      const body = await resp.text();
      return {
        content: [
          {
            type: "text",
            text: `Error: HTTP ${resp.status} — ${body.slice(0, 200)}`,
          },
        ],
      };
    }

    const result = (await resp.json()) as {
      url?: string;
      filename?: string;
      deduplicated?: boolean;
    };
    const mediaUrl = result.url
      ? result.url.startsWith("http")
        ? result.url
        : `${httpBase}${result.url}`
      : "unknown";
    const dedupeNote = result.deduplicated ? " (deduplicated)" : "";

    return {
      content: [
        {
          type: "text",
          text: `Uploaded ${filename} -> ${mediaUrl}${dedupeNote}`,
        },
      ],
    };
  } catch (err) {
    return {
      content: [{ type: "text", text: `Error: ${(err as Error).message}` }],
    };
  }
}

// ---------------------------------------------------------------------------
// Direct messages — dm_list / dm_open (todo#60 PR 4)
//
// These tools wrap the REST endpoints `/api/workspace/<slug>/dms/`. They are
// READ / CREATE only — actual message sending stays on the WS `reply` path
// (spec v3.1 §4.1: REST sender-identity for token-auth agents is unreliable;
// `reply` is the sole agent write path).
// ---------------------------------------------------------------------------

function resolveWorkspaceSlug(arg?: string): string | null {
  return (arg || process.env.SCITEX_OROCHI_WORKSPACE || "").trim() || null;
}

function dmsUrl(slug: string): string {
  return `${httpBase}/api/workspace/${encodeURIComponent(slug)}/dms/${tokenParam("?")}`;
}

export async function handleDmList(args: {
  workspace?: string;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  const slug = resolveWorkspaceSlug(args.workspace);
  if (!slug) {
    return {
      content: [
        {
          type: "text",
          text: "Error: workspace slug required. Pass workspace=<slug> or set SCITEX_OROCHI_WORKSPACE.",
        },
      ],
    };
  }
  try {
    const resp = await fetch(dmsUrl(slug), {
      method: "GET",
      headers: buildFetchHeaders(),
    });
    if (!resp.ok) {
      const body = await resp.text();
      return {
        content: [
          {
            type: "text",
            text: `Error: HTTP ${resp.status} — ${body.slice(0, 300)}`,
          },
        ],
      };
    }
    const out = await resp.json();
    return { content: [{ type: "text", text: JSON.stringify(out) }] };
  } catch (err) {
    return {
      content: [{ type: "text", text: `Error: ${(err as Error).message}` }],
    };
  }
}

export async function handleDmOpen(args: {
  recipient?: string;
  peer?: string;
  workspace?: string;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  const slug = resolveWorkspaceSlug(args.workspace);
  if (!slug) {
    return {
      content: [
        {
          type: "text",
          text: "Error: workspace slug required. Pass workspace=<slug> or set SCITEX_OROCHI_WORKSPACE.",
        },
      ],
    };
  }
  const recipient = (args.recipient || args.peer || "").trim();
  if (!recipient) {
    return {
      content: [
        {
          type: "text",
          text: "Error: recipient required (e.g. 'agent:mamba-healer-mba' or 'human:ywatanabe').",
        },
      ],
    };
  }
  try {
    const resp = await fetch(dmsUrl(slug), {
      method: "POST",
      headers: buildFetchHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ recipient }),
    });
    if (!resp.ok) {
      const body = await resp.text();
      return {
        content: [
          {
            type: "text",
            text: `Error: HTTP ${resp.status} — ${body.slice(0, 300)}`,
          },
        ],
      };
    }
    const out = await resp.json();
    /* Caller chains `reply` with chat_id=out.name to actually send. */
    return { content: [{ type: "text", text: JSON.stringify(out) }] };
  } catch (err) {
    return {
      content: [{ type: "text", text: `Error: ${(err as Error).message}` }],
    };
  }
}

// ---------------------------------------------------------------------------
// rsync_media / rsync_status: background file transfer over SSH mesh.
//
// Each job:
//  - spawns `rsync -avP --partial -e ssh <src> <dst_host>:<dst_path>` detached
//  - streams stdout+stderr to /tmp/orochi-rsync/<job_id>.log
//  - posts a completion or failure notice to the requested Orochi channel
// ---------------------------------------------------------------------------

interface RsyncJob {
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
const rsyncJobs = new Map<string, RsyncJob>();

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
      const { buildHttpBase, buildFetchHeaders, OROCHI_AGENT } =
        await import("./config.js");
      const httpBase = buildHttpBase();
      const tokenParam = process.env.SCITEX_OROCHI_TOKEN
        ? `?token=${process.env.SCITEX_OROCHI_TOKEN}`
        : "";
      await fetch(`${httpBase}/api/messages/${tokenParam}`, {
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

// ---------------------------------------------------------------------------
// connectivity_matrix — fleet 4×4 reachability matrix (todo#297 layer 3).
//
// Reads connectivity rows produced by the per-host fleet-watch producers
// (PR B, e.g. NAS `scripts/fleet-watch/fleet_watch.sh emit_connectivity_row`)
// and returns the merged matrix as JSON. Each row is a single host's
// outbound view; the merged matrix is `{from: row, ...}`.
//
// Source resolution priority:
//   1. SCITEX_OROCHI_CONNECTIVITY_DIR env var (allows tests / overrides)
//   2. ~/.scitex/orochi/fleet-watch/  (NAS-local cache, default)
//
// File names: `connectivity.json` (legacy single-row from #297 PR B initial)
// AND `connectivity-<host>.json` (multi-host pattern after Phase 2 fleet_report
// landing). Both are surfaced when present so the tool keeps working through
// the file → hub-DB migration without breaking consumers.
//
// This tool deliberately does NOT call ssh or measure RTT itself — that is
// PR B's job. This is a thin reader exposed to fleet agents via MCP so they
// can `mcp__scitex-orochi__connectivity_matrix` and get the latest snapshot
// without re-running probes.
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// sidecar_status — Orochi-side sidecar PID visibility (todo#287 Slice A).
//
// Returns a JSON snapshot of the long-lived processes that scitex-orochi
// owns from the agent's perspective:
//   - mcp_server: this bun process itself (the MCP sidecar from Claude's view)
//   - rsync_jobs: outstanding rsync_media child processes (registry maintained
//                 in `rsyncJobs` Map above)
//
// This is the orochi half of the 3-layer PID model agreed in msg#8120:
//   layer 1 (claude+tmux)        → scitex-agent-container
//   layer 2 (container daemons)  → scitex-agent-container `pids.sidecars.*`
//   layer 3 (orochi comms)       → scitex-orochi (THIS tool)
//
// fleet_watch.sh on NAS merges the scitex-agent-container `status --json`
// `pids.*` block with this tool's output to build the full per-agent PID
// matrix (msg#8120 dataflow).
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Self-command tools: send commands to the agent's own terminal session.
//
// Claude Code cannot run /compact, /clear, or exit while it is processing
// the current request. But this MCP sidecar is a separate bun process, so
// we schedule the command with setTimeout — by the time it fires, the
// agent has already received our MCP response and is idle at its prompt.
//
// The agent's terminal multiplexer is determined from SCITEX_OROCHI_MULTIPLEXER
// (screen|tmux); default is "tmux" — set SCITEX_OROCHI_MULTIPLEXER=screen to opt in.
// ---------------------------------------------------------------------------

// Allow only safe characters in the session name to prevent shell injection.
function validateSessionName(name: string): string | null {
  if (!/^[A-Za-z0-9._-]+$/.test(name)) return null;
  return name;
}

type Multiplexer = "screen" | "tmux";

function getMultiplexer(): Multiplexer {
  const m = (process.env.SCITEX_OROCHI_MULTIPLEXER || "tmux").toLowerCase();
  return m === "screen" ? "screen" : "tmux";
}

/**
 * Build the shell command that sends `text` followed by Enter into the
 * given multiplexer session. `text` should NOT contain shell metacharacters
 * beyond the slash-command payload; it is single-quoted below.
 */
function buildSendKeysCommand(
  mux: Multiplexer,
  session: string,
  text: string,
): string {
  // We single-quote text for the outer shell. Reject any text containing
  // a single quote to keep escaping trivial and injection-proof.
  if (text.includes("'")) {
    throw new Error("self-command text must not contain single quotes");
  }
  if (mux === "tmux") {
    // `tmux send-keys -l` sends literal then we send Enter separately.
    return `tmux send-keys -t '${session}' '${text}' Enter`;
  }
  // GNU screen: use `stuff` with a literal newline (\r = carriage return).
  return `screen -S '${session}' -X stuff $'${text}\\r'`;
}

function scheduleSelfCommand(
  text: string,
  delayMs: number,
  label: string,
): { content: Array<{ type: string; text: string }> } {
  const rawSession = OROCHI_AGENT;
  if (!rawSession) {
    return {
      content: [
        { type: "text", text: "ERROR: SCITEX_OROCHI_AGENT env var not set" },
      ],
    };
  }
  const session = validateSessionName(rawSession);
  if (!session) {
    return {
      content: [
        {
          type: "text",
          text: `ERROR: SCITEX_OROCHI_AGENT contains unsafe characters: ${rawSession}`,
        },
      ],
    };
  }

  const mux = getMultiplexer();
  let cmd: string;
  try {
    cmd = buildSendKeysCommand(mux, session, text);
  } catch (err) {
    return {
      content: [{ type: "text", text: `ERROR: ${(err as Error).message}` }],
    };
  }

  const delay = Math.max(0, delayMs);
  setTimeout(() => {
    exec(cmd, (err) => {
      if (err) {
        console.error(
          `[orochi] ${label} failed for session '${session}' (${mux}): ${err.message}`,
        );
      } else {
        console.error(
          `[orochi] ${label} sent '${text}' to ${mux} session '${session}'`,
        );
      }
    });
  }, delay);

  return {
    content: [
      {
        type: "text",
        text: `${label} scheduled in ${delay}ms for ${mux} session '${session}'`,
      },
    ],
  };
}

// Destructive slash commands require confirm=true.
const DESTRUCTIVE_COMMANDS = new Set(["/clear", "/kill", "/exit", "/quit"]);

// Allowlist of slash commands safe to inject via self_command.
// Modal-opening commands (/model, /agents, /permissions, /login, /config, ...)
// trap the agent in a selector dialog and require external Escape rescue, so
// they are NOT on this list. Free-text prompts (no leading '/') bypass this
// gate entirely — they just land as prompt text.
const SELF_COMMAND_ALLOWLIST: readonly string[] = [
  "/compact",
  "/clear",
  "/cost",
  "/help",
  "/status",
] as const;

// Returns true if `cmd` is safe to send via self_command.
// Free-text (no leading '/') is always safe. Slash commands are safe only if
// their first whitespace-delimited token is in SELF_COMMAND_ALLOWLIST.
export function isSafeForSelfCommand(cmd: string): boolean {
  const trimmed = (cmd || "").trim();
  if (!trimmed.startsWith("/")) {
    return true;
  }
  const slashName = trimmed.split(/\s+/, 1)[0];
  return SELF_COMMAND_ALLOWLIST.includes(slashName);
}

// Validate slash-command text. Returns error string on failure, null on OK.
function validateSelfCommand(command: string): string | null {
  if (!command || typeof command !== "string") {
    return "command is required";
  }
  // Free-text (no leading '/') is allowed — it lands as prompt text.
  if (!command.startsWith("/")) {
    if (command.includes("'")) {
      return "command must not contain single quotes (shell injection guard)";
    }
    return null;
  }
  if (command.includes("'")) {
    return "command must not contain single quotes (shell injection guard)";
  }
  if (!/^\/[A-Za-z0-9_-]+( .*)?$/.test(command)) {
    return "command must match /^\\/[A-Za-z0-9_-]+( .*)?$/";
  }
  return null;
}

export async function handleSelfCommand(args: {
  command?: string;
  delay_ms?: number;
  confirm?: boolean;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  const command = (args?.command || "").trim();
  const err = validateSelfCommand(command);
  if (err) {
    return { content: [{ type: "text", text: `ERROR: ${err}` }] };
  }

  // Allowlist gate: reject modal-opening slash commands before scheduling.
  if (!isSafeForSelfCommand(command)) {
    const rejected = command.split(/\s+/, 1)[0];
    return {
      content: [
        {
          type: "text",
          text:
            `ERROR: slash command '${rejected}' is not in self_command allowlist. ` +
            `Safe commands: ${SELF_COMMAND_ALLOWLIST.join(", ")}. ` +
            `Modal-opening commands like /model, /agents, /permissions trap the agent and are blocked. ` +
            `Free-text prompts (no leading slash) are always allowed.`,
        },
      ],
    };
  }

  // Extract the bare slash name (no args) for destructive-list lookup.
  const slashName = command.split(/\s+/, 1)[0];
  if (DESTRUCTIVE_COMMANDS.has(slashName) && !args?.confirm) {
    return {
      content: [
        {
          type: "text",
          text: `ERROR: '${slashName}' is destructive; pass confirm=true to fire`,
        },
      ],
    };
  }

  const delay = args?.delay_ms ?? 6000;
  return scheduleSelfCommand(command, delay, `self_command(${slashName})`);
}

export async function handleExportChannel(args: {
  chat_id: string;
  format?: string;
  from?: string;
  to?: string;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  const chatId = args.chat_id || "#general";
  const format = args.format || "txt";
  const params = new URLSearchParams();
  params.set("format", format);
  if (args.from) params.set("from", args.from);
  if (args.to) params.set("to", args.to);
  if (OROCHI_TOKEN) params.set("token", OROCHI_TOKEN);

  const url = `${httpBase}/api/channels/${encodeURIComponent(chatId)}/export/?${params.toString()}`;
  try {
    const resp = await fetch(url, { headers: buildFetchHeaders() });
    if (!resp.ok) {
      const body = await resp.text();
      return {
        content: [
          {
            type: "text",
            text: `Error: HTTP ${resp.status} — ${body.slice(0, 200)}`,
          },
        ],
      };
    }
    const text = await resp.text();
    return { content: [{ type: "text", text }] };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return { content: [{ type: "text", text: `Error: ${msg}` }] };
  }
}
