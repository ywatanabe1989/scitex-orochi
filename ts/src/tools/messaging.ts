/**
 * Messaging tools: reply, history, react, export_channel.
 */
import { readFileSync } from "fs";
import { basename } from "path";
import {
  ConnLike,
  MCP_ERROR_CODES,
  OROCHI_AGENT,
  OROCHI_TOKEN,
  httpBase,
  mcpError,
  tokenParam,
  buildFetchHeaders,
  MIME,
} from "./_shared.js";

export async function handleReply(
  conn: ConnLike,
  args: { chat_id: string; text: string; reply_to?: string; files?: string[] },
): Promise<{ content: Array<{ type: string; text: string }> }> {
  if (!conn.isConnected) {
    return mcpError(
      MCP_ERROR_CODES.AGENT_OFFLINE,
      `not connected to Orochi (state=${conn.state}, attempts=${(conn as any).reconnectAttempts})`,
      "wait for the MCP sidecar to reconnect",
    );
  }

  const attachments: Array<Record<string, unknown>> = [];
  if (args.files && args.files.length > 0) {
    for (const filePath of args.files) {
      try {
        const fileData = readFileSync(filePath);
        const b64 = fileData.toString("base64");
        const filename = basename(filePath);
        const ext = filename.split(".").pop()?.toLowerCase() || "";
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
  const { getRecentMessages } = await import("../message_buffer.js");
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

export async function handleReact(args: {
  message_id: number | string;
  emoji: string;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  const messageId = String(args.message_id);
  const emoji = args.emoji;
  if (!messageId || !emoji) {
    return mcpError(
      MCP_ERROR_CODES.INVALID_INPUT,
      "message_id and emoji required",
      "pass both fields",
    );
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
      const code =
        resp.status === 401 || resp.status === 403
          ? MCP_ERROR_CODES.PERMISSION_DENIED
          : resp.status === 404
            ? MCP_ERROR_CODES.NOT_FOUND
            : MCP_ERROR_CODES.INTERNAL_ERROR;
      return mcpError(
        code,
        `react HTTP ${resp.status}`,
        body.slice(0, 200) || "no response body",
      );
    }
    return {
      content: [{ type: "text", text: `reacted ${emoji} to ${messageId}` }],
    };
  } catch (err) {
    return mcpError(
      MCP_ERROR_CODES.INTERNAL_ERROR,
      `react failed: ${(err as Error).message}`,
      "check hub reachability",
    );
  }
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
      const code =
        resp.status === 401 || resp.status === 403
          ? MCP_ERROR_CODES.PERMISSION_DENIED
          : resp.status === 404
            ? MCP_ERROR_CODES.NOT_FOUND
            : MCP_ERROR_CODES.INTERNAL_ERROR;
      return mcpError(
        code,
        `export_channel HTTP ${resp.status}`,
        body.slice(0, 200) || "no response body",
      );
    }
    const text = await resp.text();
    return { content: [{ type: "text", text }] };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return mcpError(
      MCP_ERROR_CODES.INTERNAL_ERROR,
      `export_channel failed: ${msg}`,
      "check hub reachability",
    );
  }
}
