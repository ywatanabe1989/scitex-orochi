/**
 * Channel + DM tools: subscribe, unsubscribe, channel_info, dm_list, dm_open.
 *
 * DM tools wrap REST endpoints `/api/workspace/<slug>/dms/`. They are
 * READ / CREATE only — actual message sending stays on the WS `reply` path
 * (spec v3.1 §4.1: REST sender-identity for token-auth agents is unreliable;
 * `reply` is the sole agent write path).
 *
 * subscribe / unsubscribe accept an optional ``target_agent`` argument
 * (issue #262 §9.1). When present, the call routes through the admin
 * REST endpoint instead of the agent's own WS session — only useful for
 * fleet-coordinator agents whose workspace token resolves to the
 * ``admin`` (or ``staff``) role. See ``hub/views/api/_agents_subscribe.py``.
 */
import {
  ConnLike,
  MCP_ERROR_CODES,
  OROCHI_AGENT,
  httpBase,
  mcpError,
  tokenParam,
  buildFetchHeaders,
  normalizeGroupChannel,
  resolveWorkspaceSlug,
} from "./_shared.js";

/**
 * Hand off subscribe/unsubscribe to the admin REST endpoint when the
 * caller passed a ``target_agent``. The hub view enforces the admin/
 * staff role; any non-admin caller gets a structured permission_denied
 * envelope back, which we surface verbatim.
 */
async function callAdminSubscribe(
  targetAgent: string,
  channel: string,
  subscribe: boolean,
): Promise<{ content: Array<{ type: string; text: string }> }> {
  const action = subscribe ? "subscribe" : "unsubscribe";
  const encoded = encodeURIComponent(targetAgent);
  // Pass ``?agent=<self>`` so resolve_workspace_and_actor knows who's
  // making the call; the workspace token is appended by tokenParam.
  const url =
    `${httpBase}/api/agents/${encoded}/${action}/${tokenParam("?")}` +
    (tokenParam("?") ? "&" : "?") +
    "agent=" +
    encodeURIComponent(OROCHI_AGENT);
  try {
    const resp = await fetch(url, {
      method: "POST",
      headers: buildFetchHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ channel }),
    });
    const bodyText = await resp.text();
    let parsed: any = null;
    try {
      parsed = JSON.parse(bodyText);
    } catch {
      parsed = null;
    }
    if (!resp.ok) {
      // Hub returns a structured error envelope already — pass it
      // through verbatim so the caller sees the same {code, reason, hint}
      // shape regardless of which leg failed.
      if (parsed && parsed.error && typeof parsed.error.code === "string") {
        return {
          content: [{ type: "text", text: JSON.stringify(parsed) }],
        };
      }
      const code =
        resp.status === 401 || resp.status === 403
          ? MCP_ERROR_CODES.PERMISSION_DENIED
          : resp.status === 404
            ? MCP_ERROR_CODES.NOT_FOUND
            : resp.status === 400
              ? MCP_ERROR_CODES.INVALID_INPUT
              : MCP_ERROR_CODES.INTERNAL_ERROR;
      return mcpError(
        code,
        `admin ${action} HTTP ${resp.status}`,
        bodyText.slice(0, 200) || "no response body",
      );
    }
    return { content: [{ type: "text", text: bodyText }] };
  } catch (err) {
    return mcpError(
      MCP_ERROR_CODES.INTERNAL_ERROR,
      `admin ${action} request failed: ${(err as Error).message}`,
      "check hub reachability and SCITEX_OROCHI_URL",
    );
  }
}

export async function handleSubscribe(
  conn: ConnLike,
  args: { channel: string; target_agent?: string },
): Promise<{ content: Array<{ type: string; text: string }> }> {
  const channel = normalizeGroupChannel(args.channel);
  if (!channel) {
    return mcpError(
      MCP_ERROR_CODES.INVALID_INPUT,
      "channel required",
      "pass channel='#name'",
    );
  }
  const target = (args.target_agent || "").trim();
  if (target) {
    return callAdminSubscribe(target, channel, true);
  }
  if (!conn.isConnected) {
    return mcpError(
      MCP_ERROR_CODES.AGENT_OFFLINE,
      `not connected (state=${conn.state})`,
      "wait for the MCP sidecar to reconnect or check SCITEX_OROCHI_URL",
    );
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
  conn: ConnLike,
  args: { channel: string; target_agent?: string },
): Promise<{ content: Array<{ type: string; text: string }> }> {
  const channel = normalizeGroupChannel(args.channel);
  if (!channel) {
    return mcpError(
      MCP_ERROR_CODES.INVALID_INPUT,
      "channel required",
      "pass channel='#name'",
    );
  }
  const target = (args.target_agent || "").trim();
  if (target) {
    return callAdminSubscribe(target, channel, false);
  }
  if (!conn.isConnected) {
    return mcpError(
      MCP_ERROR_CODES.AGENT_OFFLINE,
      `not connected (state=${conn.state})`,
      "wait for the MCP sidecar to reconnect or check SCITEX_OROCHI_URL",
    );
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

export async function handleChannelInfo(args: {
  channel: string;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  const channel = normalizeGroupChannel(args.channel);
  if (!channel) {
    return mcpError(
      MCP_ERROR_CODES.INVALID_INPUT,
      "channel required",
      "pass channel='#name'",
    );
  }
  try {
    const url =
      `${httpBase}/api/channels/${tokenParam("?")}` +
      (tokenParam("?") ? "&" : "?") +
      "name=" +
      encodeURIComponent(channel);
    const res = await fetch(url, {
      headers: buildFetchHeaders({ Accept: "application/json" }),
    });
    if (!res.ok) {
      const code =
        res.status === 401 || res.status === 403
          ? MCP_ERROR_CODES.PERMISSION_DENIED
          : res.status === 404
            ? MCP_ERROR_CODES.NOT_FOUND
            : MCP_ERROR_CODES.INTERNAL_ERROR;
      return mcpError(
        code,
        `HTTP ${res.status} fetching channel info`,
        "verify the channel name and that the workspace token is valid",
      );
    }
    const data = await res.json();
    const match = Array.isArray(data)
      ? data.find((c: any) => c && c.name === channel)
      : null;
    if (!match) {
      return mcpError(
        MCP_ERROR_CODES.NOT_FOUND,
        `no channel named ${channel} in this workspace`,
        "use the dashboard or the channels list to confirm the name",
      );
    }
    const desc = (match.description || "").trim();
    return {
      content: [
        {
          type: "text",
          text:
            `channel: ${match.name}\n` +
            `description: ${desc || "(no description set)"}`,
        },
      ],
    };
  } catch (e) {
    return mcpError(
      MCP_ERROR_CODES.INTERNAL_ERROR,
      `channel_info failed: ${(e as Error).message}`,
      "check hub reachability",
    );
  }
}

function dmsUrl(slug: string): string {
  return `${httpBase}/api/workspace/${encodeURIComponent(slug)}/dms/${tokenParam("?")}`;
}

export async function handleDmList(args: {
  workspace?: string;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  const slug = resolveWorkspaceSlug(args.workspace);
  if (!slug) {
    return mcpError(
      MCP_ERROR_CODES.INVALID_INPUT,
      "workspace slug required",
      "pass workspace=<slug> or set SCITEX_OROCHI_WORKSPACE",
    );
  }
  try {
    const resp = await fetch(dmsUrl(slug), {
      method: "GET",
      headers: buildFetchHeaders(),
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
        `dm_list HTTP ${resp.status}`,
        body.slice(0, 200) || "no response body",
      );
    }
    const out = await resp.json();
    return { content: [{ type: "text", text: JSON.stringify(out) }] };
  } catch (err) {
    return mcpError(
      MCP_ERROR_CODES.INTERNAL_ERROR,
      `dm_list failed: ${(err as Error).message}`,
      "check hub reachability",
    );
  }
}

export async function handleDmOpen(args: {
  recipient?: string;
  peer?: string;
  workspace?: string;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  const slug = resolveWorkspaceSlug(args.workspace);
  if (!slug) {
    return mcpError(
      MCP_ERROR_CODES.INVALID_INPUT,
      "workspace slug required",
      "pass workspace=<slug> or set SCITEX_OROCHI_WORKSPACE",
    );
  }
  const recipient = (args.recipient || args.peer || "").trim();
  if (!recipient) {
    return mcpError(
      MCP_ERROR_CODES.INVALID_INPUT,
      "recipient required",
      "pass recipient='agent:<name>' or 'human:<username>'",
    );
  }
  try {
    const resp = await fetch(dmsUrl(slug), {
      method: "POST",
      headers: buildFetchHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ recipient }),
    });
    if (!resp.ok) {
      const body = await resp.text();
      const code =
        resp.status === 401 || resp.status === 403
          ? MCP_ERROR_CODES.PERMISSION_DENIED
          : resp.status === 404
            ? MCP_ERROR_CODES.NOT_FOUND
            : resp.status === 400
              ? MCP_ERROR_CODES.INVALID_INPUT
              : MCP_ERROR_CODES.INTERNAL_ERROR;
      return mcpError(
        code,
        `dm_open HTTP ${resp.status}`,
        body.slice(0, 200) || "no response body",
      );
    }
    const out = await resp.json();
    /* Caller chains `reply` with chat_id=out.name to actually send. */
    return { content: [{ type: "text", text: JSON.stringify(out) }] };
  } catch (err) {
    return mcpError(
      MCP_ERROR_CODES.INTERNAL_ERROR,
      `dm_open failed: ${(err as Error).message}`,
      "check hub reachability",
    );
  }
}
