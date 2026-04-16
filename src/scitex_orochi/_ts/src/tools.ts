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
import type { OrochiConnection } from "./connection.js";

const httpBase = buildHttpBase();

function tokenParam(prefix: "?" | "&"): string {
  return OROCHI_TOKEN ? `${prefix}token=${OROCHI_TOKEN}` : "";
}

export async function handleReply(
  conn: OrochiConnection,
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
  const channel = args.channel || "#general";
  const limit = args.limit || 10;

  try {
    const url = `${httpBase}/api/messages?channel=${encodeURIComponent(channel)}&limit=${limit}${tokenParam("&")}`;
    const resp = await fetch(url);
    if (!resp.ok) {
      return {
        content: [
          { type: "text", text: `Error: HTTP ${resp.status} from Orochi` },
        ],
      };
    }
    const messages = await resp.json();
    const formatted = (messages as Array<Record<string, string>>)
      .map(
        (m) =>
          `[${m.ts || ""}] ${m.sender || "unknown"}: ${m.content || m.text || ""}`,
      )
      .join("\n");
    return {
      content: [{ type: "text", text: formatted || "(no messages)" }],
    };
  } catch (err) {
    return {
      content: [
        {
          type: "text",
          text: `Error fetching history: ${(err as Error).message}`,
        },
      ],
    };
  }
}

function normalizeGroupChannel(name: string): string {
  const trimmed = (name || "").trim();
  if (!trimmed) return "";
  if (trimmed.startsWith("dm:") || trimmed.startsWith("#")) return trimmed;
  return `#${trimmed}`;
}

export async function handleSubscribe(
  conn: OrochiConnection,
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
  conn: OrochiConnection,
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

export function handleStatus(conn: OrochiConnection): {
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
