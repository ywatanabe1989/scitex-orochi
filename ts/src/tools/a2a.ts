/**
 * A2A protocol client tool — call peer agents via JSON-RPC.
 *
 * Posts to `https://a2a.scitex.ai/v1/agents/<agent>` with the bearer
 * read from the per-agent `.a2a-token` file (path injected via
 * SCITEX_OROCHI_A2A_TOKEN_PATH from each agent's workspace .env).
 *
 * Bearer never enters the agent transcript: the MCP server reads it
 * from disk per call and includes it in the outbound HTTP request.
 *
 * Cross-refs:
 *   - skill: scitex-orochi/_skills/scitex-orochi/51_a2a-client.md
 *   - master nav: scitex-orochi/GITIGNORED/A2A_PROTOCOL_SUPPORT.md
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
}

function readBearer(): string {
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

function buildParams(args: A2aCallArgs): Record<string, unknown> {
  if (args.params) return args.params;
  const method = args.method ?? "tasks/send";
  if (method === "tasks/send") {
    const text = args.text ?? "";
    return {
      message: {
        role: "user",
        parts: [{ type: "text", text }],
      },
    };
  }
  if (method === "tasks/get") {
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
  const method = args.method ?? "tasks/send";
  const baseUrl = (
    process.env.SCITEX_OROCHI_A2A_BASE_URL ?? DEFAULT_BASE
  ).replace(/\/+$/, "");
  const url = `${baseUrl}/v1/agents/${encodeURIComponent(args.agent)}`;
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
      headers: {
        Authorization: `Bearer ${bearer}`,
        "Content-Type": "application/json",
      },
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
