/**
 * A2A ``CancelTask`` tool — interrupt a running task (SDK 1.x).
 *
 * Phase 5 of A2A_MIGRATION.md. Maps the MCP ``task_id`` arg to the
 * proto ``id`` field. Returns the SDK envelope verbatim so the caller
 * can inspect the new task state (typically ``CANCELED``).
 */
import { a2aBaseUrl, a2aHeaders, readBearer } from "./a2a.js";

const HTTP_TIMEOUT_MS = 15_000;

interface A2aCancelTaskArgs {
  agent: string;
  task_id: string;
}

export async function handleA2aCancelTask(args: A2aCancelTaskArgs): Promise<{
  content: Array<{ type: "text"; text: string }>;
}> {
  if (!args || !args.agent) {
    throw new Error("a2a_cancel_task requires 'agent' argument");
  }
  if (!args.task_id) {
    throw new Error("a2a_cancel_task requires 'task_id' argument");
  }
  const url = `${a2aBaseUrl()}/v1/agents/${encodeURIComponent(args.agent)}`;
  const bearer = readBearer();
  const body = JSON.stringify({
    jsonrpc: "2.0",
    id: `mcp-cancel-${Date.now()}`,
    method: "CancelTask",
    params: { id: args.task_id },
  });

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), HTTP_TIMEOUT_MS);
  let resp: Response;
  try {
    resp = await fetch(url, {
      method: "POST",
      headers: a2aHeaders(bearer),
      body,
      signal: ctrl.signal,
    });
  } finally {
    clearTimeout(timer);
  }
  const text = await resp.text();
  if (!resp.ok) {
    throw new Error(`A2A ${resp.status} from ${url}: ${text.slice(0, 500)}`);
  }
  return { content: [{ type: "text", text }] };
}
