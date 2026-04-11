/**
 * In-memory rolling buffer of recent channel messages.
 *
 * The Django REST `/api/messages` endpoint requires session auth (login
 * cookie), so the MCP `history` tool can't hit it with just the workspace
 * token. Rather than add token auth to Django or ship a dashboard
 * session, we tap into the persistent WebSocket that mcp_channel.ts
 * already maintains and cache every incoming channel message in a
 * rolling buffer. `handleHistory` then reads from this buffer.
 *
 * Since the MCP server starts freshly for each agent session, the
 * buffer only has messages that arrived AFTER the agent connected.
 * That is fine for the main use case (responding to @mentions in
 * real time); for deeper history the user can still use the dashboard.
 */

export interface BufferedMessage {
  id: number | string | null;
  channel: string;
  sender: string;
  content: string;
  ts: string;
  metadata?: Record<string, unknown>;
}

const BUFFER_SIZE = 500;
const buffer: BufferedMessage[] = [];

export function addMessage(entry: BufferedMessage): void {
  buffer.push(entry);
  if (buffer.length > BUFFER_SIZE) {
    buffer.shift();
  }
}

export function getRecentMessages(
  channel: string | undefined,
  limit: number,
): BufferedMessage[] {
  const normalizedChannel = channel
    ? channel.startsWith("#")
      ? channel
      : `#${channel}`
    : undefined;

  const filtered = normalizedChannel
    ? buffer.filter((m) => m.channel === normalizedChannel)
    : buffer;

  return filtered.slice(-Math.max(1, limit));
}

export function getBufferSize(): number {
  return buffer.length;
}
