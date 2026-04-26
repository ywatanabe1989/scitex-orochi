/**
 * A2A streaming tool — ``SendStreamingMessage`` over SSE.
 *
 * Phase 5 of A2A_MIGRATION.md. Posts to
 * ``POST /v1/agents/<agent>`` with method ``SendStreamingMessage`` and
 * accumulates the SSE event stream into a single MCP tool result.
 *
 * Limitation: the MCP TypeScript SDK (``@modelcontextprotocol/sdk``
 * ^1.29.0) used by this server returns tool results synchronously
 * from a single ``CallToolRequestSchema`` handler — there is no
 * incremental-output API exposed here. So we collect all SSE events
 * in memory and return a JSON array of events at end-of-stream.
 *
 * If/when the MCP SDK exposes streaming tool output cleanly, this
 * function should pipe events as they arrive. Tracked alongside Phase 6
 * (push-notification MCP wiring).
 */
import { a2aBaseUrl, a2aHeaders, readBearer } from "./a2a.js";

const HTTP_TIMEOUT_MS = 60_000; // streaming may take longer than unary
const MAX_EVENTS = 256; // safety cap so a runaway agent can't OOM the sidecar

interface A2aStreamArgs {
  agent: string;
  text: string;
  message_id?: string;
}

export async function handleA2aSendStreaming(args: A2aStreamArgs): Promise<{
  content: Array<{ type: "text"; text: string }>;
}> {
  if (!args || !args.agent) {
    throw new Error("a2a_send_streaming requires 'agent' argument");
  }
  const text = args.text ?? "";
  const url = `${a2aBaseUrl()}/v1/agents/${encodeURIComponent(args.agent)}`;
  const bearer = readBearer();
  const body = JSON.stringify({
    jsonrpc: "2.0",
    id: `mcp-stream-${Date.now()}`,
    method: "SendStreamingMessage",
    params: {
      message: {
        message_id: args.message_id ?? `mcp-stream-msg-${Date.now()}`,
        role: "ROLE_USER",
        parts: [{ text }],
      },
    },
  });

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), HTTP_TIMEOUT_MS);
  let resp: Response;
  try {
    resp = await fetch(url, {
      method: "POST",
      headers: { ...a2aHeaders(bearer), Accept: "text/event-stream" },
      body,
      signal: ctrl.signal,
    });
  } catch (e) {
    clearTimeout(timer);
    throw e;
  }

  if (!resp.ok) {
    clearTimeout(timer);
    const errText = await resp.text();
    throw new Error(
      `A2A ${resp.status} from ${url}: ${errText.slice(0, 500)}`,
    );
  }
  if (!resp.body) {
    clearTimeout(timer);
    throw new Error(`A2A streaming response from ${url} has no body`);
  }

  const events: unknown[] = [];
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  try {
    while (events.length < MAX_EVENTS) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      // SSE frames are separated by blank lines; each frame may have
      // multiple ``data:`` lines. We extract one JSON object per
      // ``data:`` line (matching sac's test client).
      let nl: number;
      while ((nl = buf.indexOf("\n")) !== -1) {
        const line = buf.slice(0, nl).replace(/\r$/, "");
        buf = buf.slice(nl + 1);
        if (!line.startsWith("data:")) continue;
        const payload = line.slice("data:".length).trim();
        if (!payload) continue;
        try {
          events.push(JSON.parse(payload));
        } catch {
          events.push({ raw: payload });
        }
        if (events.length >= MAX_EVENTS) break;
      }
    }
  } finally {
    clearTimeout(timer);
    try {
      reader.releaseLock();
    } catch {
      // ignore
    }
  }

  return {
    content: [
      {
        type: "text",
        text: JSON.stringify({ events, count: events.length }, null, 2),
      },
    ],
  };
}
