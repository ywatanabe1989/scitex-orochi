/**
 * Agent status / lifecycle tools: health, task, subagents, status, context.
 */
import { readFileSync, unlinkSync } from "fs";
import { execSync } from "child_process";
import {
  ConnLike,
  MCP_ERROR_CODES,
  OROCHI_AGENT,
  httpBase,
  mcpError,
  tokenParam,
  buildFetchHeaders,
  buildWsUrl,
  maskUrl,
} from "./_shared.js";

export async function handleHealth(args: {
  agent?: string;
  status?: string;
  reason?: string;
  source?: string;
  updates?: Array<{
    agent: string;
    status: string;
    reason?: string;
    source?: string;
  }>;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  try {
    const url = `${httpBase}/api/agents/health/${tokenParam("?")}`;
    const body: Record<string, unknown> = {};
    if (args.updates) body.updates = args.updates;
    else {
      if (!args.agent || !args.status) {
        return mcpError(
          MCP_ERROR_CODES.INVALID_INPUT,
          "agent and status required (or pass updates[])",
          "include both fields, or send a list under 'updates'",
        );
      }
      body.agent = args.agent;
      body.status = args.status;
      if (args.reason) body.reason = args.reason;
      if (args.source) body.source = args.source;
      else body.source = OROCHI_AGENT;
    }
    const resp = await fetch(url, {
      method: "POST",
      headers: buildFetchHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const t = await resp.text();
      const code =
        resp.status === 401 || resp.status === 403
          ? MCP_ERROR_CODES.PERMISSION_DENIED
          : resp.status === 404
            ? MCP_ERROR_CODES.NOT_FOUND
            : MCP_ERROR_CODES.INTERNAL_ERROR;
      return mcpError(
        code,
        `health HTTP ${resp.status}`,
        t.slice(0, 200) || "no response body",
      );
    }
    const out = (await resp.json()) as { applied?: number };
    return {
      content: [{ type: "text", text: `health applied: ${out.applied ?? 0}` }],
    };
  } catch (err) {
    return mcpError(
      MCP_ERROR_CODES.INTERNAL_ERROR,
      `health failed: ${(err as Error).message}`,
      "check hub reachability",
    );
  }
}

export async function handleTask(
  conn: ConnLike,
  args: { task: string },
): Promise<{ content: Array<{ type: string; text: string }> }> {
  if (!conn.isConnected) {
    return mcpError(
      MCP_ERROR_CODES.AGENT_OFFLINE,
      `not connected (state=${conn.state})`,
      "wait for the MCP sidecar to reconnect",
    );
  }
  const task = (args.task || "").slice(0, 200);
  conn.send(
    JSON.stringify({
      type: "task_update",
      sender: OROCHI_AGENT,
      payload: { task },
    }),
  );
  return { content: [{ type: "text", text: `task: ${task}` }] };
}

export async function handleSubagents(
  conn: ConnLike,
  args: { subagents: Array<{ name?: string; task?: string; status?: string }> },
): Promise<{ content: Array<{ type: string; text: string }> }> {
  if (!conn.isConnected) {
    return mcpError(
      MCP_ERROR_CODES.AGENT_OFFLINE,
      `not connected (state=${conn.state})`,
      "wait for the MCP sidecar to reconnect",
    );
  }
  const list = Array.isArray(args.subagents) ? args.subagents : [];
  conn.send(
    JSON.stringify({
      type: "subagents_update",
      sender: OROCHI_AGENT,
      payload: { subagents: list },
    }),
  );
  return {
    content: [{ type: "text", text: `reported ${list.length} subagent(s)` }],
  };
}

export async function handleContext(args: {
  screen_name?: string;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  const screenName = args.screen_name || OROCHI_AGENT;
  const tmpFile = `/tmp/screen-context-${screenName}.txt`;
  try {
    // Capture screen hardcopy
    execSync(`screen -S ${screenName} -X hardcopy ${tmpFile}`, {
      timeout: 5000,
    });
    const raw = readFileSync(tmpFile, "utf-8");
    try {
      unlinkSync(tmpFile);
    } catch {}

    // Parse context percentage from statusline.
    // claude-hud formats like "42% (2h 15m / 5h)" or just "42%"
    const lines = raw.split("\n").filter((l) => l.trim());
    // Search from bottom up — statusline is typically the last non-empty line
    let contextPercent: number | null = null;
    let rawStatusline = "";
    for (let i = lines.length - 1; i >= Math.max(0, lines.length - 5); i--) {
      const line = lines[i];
      const match = line.match(/(\d+)%/);
      if (match) {
        contextPercent = parseInt(match[1], 10);
        rawStatusline = line.trim();
        break;
      }
    }

    if (contextPercent === null) {
      return mcpError(
        MCP_ERROR_CODES.NOT_FOUND,
        `could not parse context percentage from screen "${screenName}"`,
        `last lines: ${lines.slice(-3).join(" | ").slice(0, 200)}`,
      );
    }

    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            context_percent: contextPercent,
            raw_statusline: rawStatusline,
          }),
        },
      ],
    };
  } catch (err) {
    return mcpError(
      MCP_ERROR_CODES.AGENT_OFFLINE,
      `failed to read screen "${screenName}": ${(err as Error).message}`,
      "ensure the screen/tmux session for this agent is alive on its host",
    );
  }
}

export function handleStatus(conn: ConnLike): {
  content: Array<{ type: string; text: string }>;
} {
  const uptime = conn.lastConnectedAt
    ? Math.round((Date.now() - (conn.lastConnectedAt as any).getTime()) / 1000)
    : 0;
  return {
    content: [
      {
        type: "text",
        text: [
          `state: ${conn.state}`,
          `agent: ${OROCHI_AGENT}`,
          `url: ${maskUrl(buildWsUrl())}`,
          `connected_since: ${(conn.lastConnectedAt as any)?.toISOString() || "never"}`,
          `uptime_seconds: ${conn.state === "connected" ? uptime : 0}`,
          `reconnect_attempts: ${(conn as any).reconnectAttempts}`,
          `total_reconnects: ${(conn as any).totalReconnects}`,
          `last_pong_age_ms: ${(conn as any).lastPongAgeMs ?? "n/a"}`,
        ].join("\n"),
      },
    ],
  };
}
