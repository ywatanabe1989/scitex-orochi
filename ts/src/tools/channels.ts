/**
 * Channel + DM tools: subscribe, unsubscribe, channel_info, dm_list, dm_open.
 *
 * DM tools wrap REST endpoints `/api/workspace/<slug>/dms/`. They are
 * READ / CREATE only — actual message sending stays on the WS `reply` path
 * (spec v3.1 §4.1: REST sender-identity for token-auth agents is unreliable;
 * `reply` is the sole agent write path).
 */
import {
  ConnLike,
  OROCHI_AGENT,
  httpBase,
  tokenParam,
  buildFetchHeaders,
  normalizeGroupChannel,
  resolveWorkspaceSlug,
} from "./_shared.js";

export async function handleSubscribe(
  conn: ConnLike,
  args: { channel: string },
): Promise<{ content: Array<{ type: string; text: string }> }> {
  const channel = normalizeGroupChannel(args.channel);
  if (!channel) {
    return { content: [{ type: "text", text: "Error: channel required" }] };
  }
  if (!conn.isConnected) {
    return {
      content: [
        { type: "text", text: `Error: not connected (state=${conn.state})` },
      ],
    };
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
  args: { channel: string },
): Promise<{ content: Array<{ type: string; text: string }> }> {
  const channel = normalizeGroupChannel(args.channel);
  if (!channel) {
    return { content: [{ type: "text", text: "Error: channel required" }] };
  }
  if (!conn.isConnected) {
    return {
      content: [
        { type: "text", text: `Error: not connected (state=${conn.state})` },
      ],
    };
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
    return { content: [{ type: "text", text: "Error: channel required" }] };
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
      return {
        content: [
          {
            type: "text",
            text: `Error: HTTP ${res.status} fetching channel info`,
          },
        ],
      };
    }
    const data = await res.json();
    const match = Array.isArray(data)
      ? data.find((c: any) => c && c.name === channel)
      : null;
    if (!match) {
      return {
        content: [
          {
            type: "text",
            text: `(no channel named ${channel} in this workspace)`,
          },
        ],
      };
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
    return {
      content: [{ type: "text", text: `Error fetching channel info: ${e}` }],
    };
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
    return {
      content: [
        {
          type: "text",
          text: "Error: workspace slug required. Pass workspace=<slug> or set SCITEX_OROCHI_WORKSPACE.",
        },
      ],
    };
  }
  try {
    const resp = await fetch(dmsUrl(slug), {
      method: "GET",
      headers: buildFetchHeaders(),
    });
    if (!resp.ok) {
      const body = await resp.text();
      return {
        content: [
          {
            type: "text",
            text: `Error: HTTP ${resp.status} — ${body.slice(0, 300)}`,
          },
        ],
      };
    }
    const out = await resp.json();
    return { content: [{ type: "text", text: JSON.stringify(out) }] };
  } catch (err) {
    return {
      content: [{ type: "text", text: `Error: ${(err as Error).message}` }],
    };
  }
}

export async function handleChannelMembers(args: {
  channel: string;
  workspace?: string;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  const channel = normalizeGroupChannel(args.channel);
  if (!channel) {
    return { content: [{ type: "text", text: "Error: channel required" }] };
  }
  const slug = resolveWorkspaceSlug(args.workspace);
  if (!slug) {
    return {
      content: [
        {
          type: "text",
          text:
            "Error: workspace slug required. Pass workspace=<slug> or set " +
            "SCITEX_OROCHI_WORKSPACE.",
        },
      ],
    };
  }
  try {
    const url =
      `${httpBase}/api/workspace/${encodeURIComponent(slug)}` +
      `/channel-members/${tokenParam("?")}` +
      (tokenParam("?") ? "&" : "?") +
      "channel=" +
      encodeURIComponent(channel);
    const res = await fetch(url, {
      headers: buildFetchHeaders({ Accept: "application/json" }),
    });
    if (!res.ok) {
      const body = await res.text();
      return {
        content: [
          {
            type: "text",
            text: `Error: HTTP ${res.status} — ${body.slice(0, 300)}`,
          },
        ],
      };
    }
    const raw = await res.json();
    /* Hub returns rows of {username, permission, kind, role}. Reshape
     * to the spec'd MCP tool surface: {name, principal_type, role}.
     * `name` strips the "agent-" prefix so it matches the agent-name
     * convention used elsewhere (matches identity_name on DM rows). */
    const rows = Array.isArray(raw) ? raw : [];
    const members = rows.map((m: any) => {
      const username = String(m.username || "");
      const principal_type = m.kind === "agent" ? "agent" : "human";
      const name =
        principal_type === "agent" && username.startsWith("agent-")
          ? username.slice("agent-".length)
          : username;
      return {
        name,
        principal_type,
        role: m.permission || m.role || "",
      };
    });
    return { content: [{ type: "text", text: JSON.stringify(members) }] };
  } catch (e) {
    return {
      content: [{ type: "text", text: `Error fetching channel members: ${e}` }],
    };
  }
}

export async function handleMySubscriptions(args: {
  workspace?: string;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  const slug = resolveWorkspaceSlug(args.workspace);
  if (!slug) {
    return {
      content: [
        {
          type: "text",
          text:
            "Error: workspace slug required. Pass workspace=<slug> or set " +
            "SCITEX_OROCHI_WORKSPACE.",
        },
      ],
    };
  }
  try {
    const url =
      `${httpBase}/api/workspace/${encodeURIComponent(slug)}` +
      `/me/subscriptions/${tokenParam("?")}`;
    const res = await fetch(url, {
      headers: buildFetchHeaders({ Accept: "application/json" }),
    });
    if (!res.ok) {
      const body = await res.text();
      return {
        content: [
          {
            type: "text",
            text: `Error: HTTP ${res.status} — ${body.slice(0, 300)}`,
          },
        ],
      };
    }
    const out = await res.json();
    return { content: [{ type: "text", text: JSON.stringify(out) }] };
  } catch (e) {
    return {
      content: [{ type: "text", text: `Error fetching subscriptions: ${e}` }],
    };
  }
}

export async function handleDmOpen(args: {
  recipient?: string;
  peer?: string;
  workspace?: string;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  const slug = resolveWorkspaceSlug(args.workspace);
  if (!slug) {
    return {
      content: [
        {
          type: "text",
          text: "Error: workspace slug required. Pass workspace=<slug> or set SCITEX_OROCHI_WORKSPACE.",
        },
      ],
    };
  }
  const recipient = (args.recipient || args.peer || "").trim();
  if (!recipient) {
    return {
      content: [
        {
          type: "text",
          text: "Error: recipient required (e.g. 'agent:mamba-healer-mba' or 'human:ywatanabe').",
        },
      ],
    };
  }
  try {
    const resp = await fetch(dmsUrl(slug), {
      method: "POST",
      headers: buildFetchHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ recipient }),
    });
    if (!resp.ok) {
      const body = await resp.text();
      return {
        content: [
          {
            type: "text",
            text: `Error: HTTP ${resp.status} — ${body.slice(0, 300)}`,
          },
        ],
      };
    }
    const out = await resp.json();
    /* Caller chains `reply` with chat_id=out.name to actually send. */
    return { content: [{ type: "text", text: JSON.stringify(out) }] };
  } catch (err) {
    return {
      content: [{ type: "text", text: `Error: ${(err as Error).message}` }],
    };
  }
}
