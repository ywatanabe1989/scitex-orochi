/**
 * Inbound WebSocket message dispatch — handle ping/pong, thread replies,
 * reaction updates, dedup, mention filtering, attachment normalization, and
 * deliver as MCP `notifications/claude/channel`.
 */
import type { Server } from "@modelcontextprotocol/sdk/server/index.js";
import type WebSocket from "ws";
import { OROCHI_AGENT } from "../src/config.js";
import { addMessage } from "../src/message_buffer.js";
import {
  refreshIssueTitleCache,
  decorateIssueRefs,
} from "../src/issue_cache.js";
import { dbg } from "./guards.js";

// Dedup: track recently delivered message IDs to prevent duplicate notifications
const _deliveredIds = new Set<string | number>();

function rememberDelivered(msgId: string | number): boolean {
  if (_deliveredIds.has(msgId)) return false;
  _deliveredIds.add(msgId);
  if (_deliveredIds.size > 100) {
    const iter = _deliveredIds.values();
    for (let i = 0; i < 50; i++) iter.next();
    const keep = new Set<string | number>();
    for (const v of iter) keep.add(v);
    _deliveredIds.clear();
    for (const v of keep) _deliveredIds.add(v);
  }
  return true;
}

function resolveHubBase(): string {
  // Derive hubBase from SCITEX_OROCHI_URL (public wss://host/...) so
  // agent notifications carry a browser-reachable absolute URL rather
  // than the internal localhost:8559 default. Fall back to env HOST/PORT
  // for LAN dev, and finally to localhost:8559 as a last resort.
  const _orochiUrl = process.env.SCITEX_OROCHI_URL || "";
  if (_orochiUrl) {
    try {
      const u = new URL(_orochiUrl);
      const scheme = u.protocol === "wss:" ? "https:" : "http:";
      return `${scheme}//${u.host}`;
    } catch {
      /* fall through */
    }
  }
  return `http://${process.env.SCITEX_OROCHI_HOST || "localhost"}:${process.env.SCITEX_OROCHI_PORT || "8559"}`;
}

function normalizeAttachments(msg: any, payload: any): string {
  let attachmentInfo = "";
  try {
    const rawAttachments =
      (msg.metadata && msg.metadata.attachments) ||
      msg.attachments ||
      payload.attachments ||
      [];
    const hubBase = resolveHubBase();
    const attachments: Array<{ url: string; filename: string }> = [];
    for (const a of rawAttachments as unknown[]) {
      try {
        if (a == null || typeof a !== "object") continue;
        const att = a as Record<string, unknown>;
        const u = typeof att.url === "string" ? att.url : "";
        if (!u) continue; // skip attachments with no url
        const abs = u.startsWith("http") ? u : hubBase.replace(/\/$/, "") + u;
        const filename =
          typeof att.filename === "string" ? att.filename : "file";
        attachments.push({ url: abs, filename });
      } catch (attErr) {
        dbg(`skipping malformed attachment: ${attErr}`);
      }
    }
    if (attachments.length > 0) {
      // Cap attachment list to avoid oversized notifications
      const shown = attachments.slice(0, 10);
      const extra =
        attachments.length > 10 ? ` (+${attachments.length - 10} more)` : "";
      attachmentInfo = `\n[Attachments: ${shown
        .map((a) => `${a.filename} -> ${a.url}`)
        .join(", ")}${extra}]`;
    }
  } catch (attNormErr) {
    dbg(`attachment normalization failed: ${attNormErr}`);
  }
  return attachmentInfo;
}

async function deliverWithRetry(
  mcp: Server,
  notifPayload: any,
  channel: string,
  sender: string,
): Promise<void> {
  // Retry with exponential backoff (pattern from official Discord plugin).
  // Claude Code can silently drop notifications; retrying mitigates this.
  const delays = [0, 500, 1000];
  let delivered = false;
  for (let attempt = 0; attempt < delays.length; attempt++) {
    if (attempt > 0) await new Promise((r) => setTimeout(r, delays[attempt]));
    try {
      await mcp.notification(notifPayload);
      dbg(
        `notification sent OK (attempt ${attempt + 1}): ${channel} ${sender}`,
      );
      delivered = true;
      break;
    } catch (retryErr) {
      dbg(`notification attempt ${attempt + 1} failed: ${retryErr}`);
    }
  }
  if (!delivered) {
    console.error(
      `[orochi] all notification attempts failed for ${channel} ${sender}`,
    );
  }
}

export async function handleWsMessage(
  mcp: Server,
  ws: WebSocket,
  data: Buffer,
): Promise<void> {
  const raw = data.toString();
  try {
    dbg(`ws recv: ${raw.slice(0, 200)}`);
    const msg = JSON.parse(raw);

    // todo#46 — hub→agent JSON ping. Echo original ts back so the
    // hub can compute RTT and light the Agents-tab RT lamp. Keep
    // this branch first so ping handling is not blocked by any
    // later message-type routing.
    if (msg.type === "ping") {
      const sentTs =
        typeof msg.ts === "number"
          ? msg.ts
          : typeof msg?.payload?.ts === "number"
            ? msg.payload.ts
            : null;
      if (sentTs !== null) {
        try {
          ws.send(JSON.stringify({ type: "pong", payload: { ts: sentTs } }));
        } catch (_) {
          /* socket already closing — ignore */
        }
      }
      return;
    }

    // Thread replies and reaction updates -> rewrite to message type
    if (msg.type === "thread_reply") {
      const parentId = msg.parent_id ?? msg.parent ?? "?";
      msg.type = "message";
      msg.text = `\u21b3 reply to msg#${parentId}: ${msg.text || msg.content || ""}`;
    } else if (msg.type === "reaction_update") {
      const targetId = msg.message_id ?? msg.target ?? "?";
      const emoji = msg.emoji || "?";
      const action = msg.action || (msg.added ? "added" : "removed");
      msg.type = "message";
      msg.text = `${action === "removed" ? "\u2796" : "\u2795"} ${emoji} on msg#${targetId}`;
      msg.sender = msg.actor || msg.sender || "unknown";
    } else if (msg.type !== "message") {
      return;
    }

    const payload = msg.payload || {};
    const content =
      msg.text ||
      msg.content ||
      payload.content ||
      payload.text ||
      payload.message ||
      "";
    const sender = msg.sender || payload.sender || "unknown";
    const channel = msg.channel || payload.channel || "";

    addMessage({
      id: msg.id ?? payload.id ?? null,
      channel: channel,
      sender: sender,
      content: content,
      ts: msg.ts || new Date().toISOString(),
      metadata: msg.metadata || payload.metadata || {},
    });

    if (sender === OROCHI_AGENT || !content) {
      dbg(
        `skipped: sender=${sender} agent=${OROCHI_AGENT} content=${!!content}`,
      );
      return;
    }

    // Dedup
    const msgId = msg.id ?? payload.id;
    if (msgId != null) {
      if (!rememberDelivered(msgId)) {
        dbg(`dedup: skipping duplicate msg ${msgId}`);
        return;
      }
    }

    // @mention filtering: only deliver messages addressed to this agent
    const mentions = content.match(/@(\w[\w-]*)/g);
    if (mentions && mentions.length > 0) {
      const mentionedNames = mentions.map((m: string) =>
        m.slice(1).toLowerCase(),
      );
      const myName = OROCHI_AGENT.toLowerCase();
      if (!mentionedNames.includes(myName) && !mentionedNames.includes("all")) {
        dbg(
          `mention-filter: skipping msg for [${mentionedNames.join(",")}], I am ${OROCHI_AGENT}`,
        );
        return;
      }
    }

    dbg(
      `delivering: sender=${sender} channel=${channel} content=${content.slice(0, 50)} id=${msgId}`,
    );

    const attachmentInfo = normalizeAttachments(msg, payload);

    refreshIssueTitleCache();
    const decoratedContent = decorateIssueRefs(content);

    const notifContent = `${decoratedContent}${attachmentInfo}`;
    // Meta values must all be strings — Claude Code ignores
    // notifications where meta contains non-string values (numbers, null).
    const notifMeta: Record<string, string> = {
      chat_id: channel || "#general",
      user: sender,
      ts: msg.ts || new Date().toISOString(),
    };
    const msgIdVal = msg.id ?? payload.id;
    if (msgIdVal != null) notifMeta.msg_id = String(msgIdVal);

    const notifPayload = {
      method: "notifications/claude/channel" as const,
      params: { content: notifContent, meta: notifMeta },
    };
    await deliverWithRetry(mcp, notifPayload, channel, sender);
  } catch (e) {
    const errMsg = e instanceof Error ? e.message : String(e);
    dbg(`error: ${errMsg}`);
    console.error(`[orochi] message handler error: ${errMsg}`);
  }
}
