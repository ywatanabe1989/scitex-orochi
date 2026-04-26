/**
 * A2A ``GetTask`` tool — poll a long-running task by id (SDK 1.x).
 *
 * Phase 5 of A2A_MIGRATION.md. Companion to ``a2a_send_streaming`` /
 * ``a2a_call``: once a peer agent returns a task id, callers use this
 * to fetch the latest task state (status + artifacts) without holding
 * the SSE stream open.
 */
import { a2aBaseUrl, a2aHeaders, readBearer } from "./a2a.js";

const HTTP_TIMEOUT_MS = 15_000;

interface A2aGetTaskArgs {
  agent: string;
  task_id: string;
}

export async function handleA2aGetTask(args: A2aGetTaskArgs): Promise<{
  content: Array<{ type: "text"; text: string }>;
}> {
  if (!args || !args.agent) {
    throw new Error("a2a_get_task requires 'agent' argument");
  }
  if (!args.task_id) {
    throw new Error("a2a_get_task requires 'task_id' argument");
  }
  const url = `${a2aBaseUrl()}/v1/agents/${encodeURIComponent(args.agent)}`;
  const bearer = readBearer();
  const body = JSON.stringify({
    jsonrpc: "2.0",
    id: `mcp-get-${Date.now()}`,
    method: "GetTask",
    // SDK 1.x: GetTask params take ``{id}`` (proto field name).
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
