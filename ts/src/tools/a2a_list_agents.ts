/**
 * A2A ``list_agents`` tool — enumerate callable agents (SDK 1.x).
 *
 * Hits the orochi hub registry endpoint so the LLM does not have to
 * guess agent names before issuing ``a2a_call`` /
 * ``a2a_send_streaming``.
 *
 * URL choice: ``GET /api/agents/`` is the canonical hub endpoint that
 * powers the Agents tab (see ``hub/urls.py:112`` →
 * ``views.api_agents``). The orochi A2A surface at
 * ``/v1/agents/`` (sac-side AgentCard discovery) is the public
 * equivalent on the cloud side; for the MCP sidecar we prefer the hub
 * registry because it is the authoritative source of liveness +
 * workspace scoping (and the bearer orochi_model already authenticates the
 * sidecar to the hub, no second token needed).
 *
 * Override via ``SCITEX_OROCHI_AGENTS_LIST_URL`` if a deployment puts
 * the registry behind a different path.
 */
import { buildHttpBase, buildFetchHeaders } from "../config.js";

const HTTP_TIMEOUT_MS = 10_000;

export async function handleA2aListAgents(): Promise<{
  content: Array<{ type: "text"; text: string }>;
}> {
  const override = process.env.SCITEX_OROCHI_AGENTS_LIST_URL;
  const base = buildHttpBase().replace(/\/+$/, "");
  const url = override && override.trim().length > 0
    ? override
    : `${base}/api/agents/`;

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), HTTP_TIMEOUT_MS);
  let resp: Response;
  try {
    resp = await fetch(url, {
      method: "GET",
      headers: buildFetchHeaders({ Accept: "application/json" }),
      signal: ctrl.signal,
    });
  } finally {
    clearTimeout(timer);
  }
  const text = await resp.text();
  if (!resp.ok) {
    throw new Error(
      `a2a_list_agents ${resp.status} from ${url}: ${text.slice(0, 500)}`,
    );
  }
  return { content: [{ type: "text", text }] };
}
