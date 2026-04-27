/**
 * A2A protocol client tool — call peer agents via JSON-RPC (SDK 1.x).
 *
 * Posts to `https://a2a.scitex.ai/v1/agents/<agent>` with the bearer
 * read from the per-agent `.a2a-token` file (path injected via
 * SCITEX_OROCHI_A2A_TOKEN_PATH from each agent's workspace .env).
 *
 * Bearer never enters the agent transcript: the MCP server reads it
 * from disk per call and includes it in the outbound HTTP request.
 *
 * SDK 1.x alignment (Phase 5 of A2A_MIGRATION.md):
 *   - default method → ``SendMessage`` (not legacy ``tasks/send``)
 *   - polling      → ``GetTask`` (params: ``{id}``)
 *   - proto snake_case message fields (``message_id``, ``task_id``)
 *   - ``A2A-Version: 1.0`` header on every outbound request
 *
 * Cross-refs:
 *   - skill: scitex-orochi/_skills/scitex-orochi/51_a2a-client.md
 *   - master nav: scitex-orochi/GITIGNORED/A2A_MIGRATION.md (Phase 5)
 *   - sac SDK reference: /tmp/wt-sac-a2a/tests/test_a2a_server.py
 */
import { readFileSync } from "node:fs";

const DEFAULT_BASE = "https://a2a.scitex.ai";
const HTTP_TIMEOUT_MS = 15_000;

interface A2aCallArgs {
  agent: string;
  method?: string;
  text?: string;
  params?: Record<string, unknown>;
  task_id?: string;
  message_id?: string;
}

export function readBearer(): string {
  const path = process.env.SCITEX_OROCHI_A2A_TOKEN_PATH;
  if (!path) {
    throw new Error(
      "SCITEX_OROCHI_A2A_TOKEN_PATH is not set (expected from <workdir>/.env via sac deploy_src_env)",
    );
  }
  try {
    return readFileSync(path, "utf8").trim();
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    throw new Error(`Failed to read A2A token at ${path}: ${msg}`);
  }
}

export function a2aBaseUrl(): string {
  return (process.env.SCITEX_OROCHI_A2A_BASE_URL ?? DEFAULT_BASE).replace(
    /\/+$/,
    "",
  );
}

export function a2aHeaders(bearer: string): Record<string, string> {
  return {
    Authorization: `Bearer ${bearer}`,
    "Content-Type": "application/json",
    "A2A-Version": "1.0",
  };
}

function buildParams(args: A2aCallArgs): Record<string, unknown> {
  if (args.params) return args.params;
  const method = args.method ?? "SendMessage";
  if (method === "SendMessage" || method === "SendStreamingMessage") {
    const text = args.text ?? "";
    return {
      message: {
        message_id: args.message_id ?? `mcp-msg-${Date.now()}`,
        role: "ROLE_USER",
        parts: [{ text }],
      },
    };
  }
  if (method === "GetTask" || method === "CancelTask") {
    // SDK 1.x: GetTask/CancelTask take ``{id}``; we accept ``task_id`` from
    // the caller and map it to the proto-style ``id`` field.
    return { id: args.task_id ?? "" };
  }
  return {};
}

export async function handleA2aCall(args: A2aCallArgs): Promise<{
  content: Array<{ type: "text"; text: string }>;
}> {
  if (!args || !args.agent) {
    throw new Error("a2a_call requires 'agent' argument");
  }
  const method = args.method ?? "SendMessage";
  const url = `${a2aBaseUrl()}/v1/agents/${encodeURIComponent(args.agent)}`;
  const bearer = readBearer();
  const body = JSON.stringify({
    jsonrpc: "2.0",
    id: `mcp-${Date.now()}`,
    method,
    params: buildParams(args),
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
