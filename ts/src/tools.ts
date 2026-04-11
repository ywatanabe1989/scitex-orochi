/**
 * MCP tool handlers for Orochi push client: reply, history, status.
 */
import { readFileSync } from "fs";
import { basename } from "path";
import {
  OROCHI_AGENT,
  OROCHI_TOKEN,
  buildHttpBase,
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
        const resp = await fetch(
          `${httpBase}/api/upload-base64${tokenParam("?")}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ data: b64, filename }),
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

  const payload: Record<string, unknown> = {
    channel: args.chat_id,
    text: args.text,
    metadata: args.reply_to ? { reply_to: args.reply_to } : {},
  };
  if (attachments.length > 0) payload.attachments = attachments;

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
    .map(
      (m) =>
        `[${m.ts}] ${m.sender}${m.id !== null ? ` (msg#${m.id})` : ""}: ${m.content}`,
    )
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
      headers: { "Content-Type": "application/json" },
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
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message_id: Number(messageId), emoji }),
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
