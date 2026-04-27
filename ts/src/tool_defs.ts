/**
 * MCP tool definitions for the Orochi channel server.
 */
export const TOOL_DEFS = [
  {
    name: "reply",
    description:
      "Send a message to an Orochi channel. Pass chat_id from the inbound <channel> tag.",
    inputSchema: {
      type: "object" as const,
      properties: {
        chat_id: {
          type: "string",
          description: "The channel to send to (e.g. #general).",
        },
        text: { type: "string", description: "The message text to send." },
        reply_to: {
          type: "string",
          description: "Optional: message ID to reply to.",
        },
        files: {
          type: "array",
          items: { type: "string" },
          description: "Optional: absolute file paths to attach.",
        },
      },
      required: ["chat_id", "text"],
    },
  },
  {
    name: "history",
    description: "Get recent message history from an Orochi channel.",
    inputSchema: {
      type: "object" as const,
      properties: {
        channel: {
          type: "string",
          description: "Channel name (default: #general).",
        },
        limit: {
          type: "number",
          description: "Max messages to return (default: 10).",
        },
      },
    },
  },
  {
    name: "health",
    description:
      "Record a health diagnosis for an agent. Status: healthy|idle|stale|stuck_prompt|dead|ghost|remediating|unknown.",
    inputSchema: {
      type: "object" as const,
      properties: {
        agent: { type: "string", description: "Target agent name" },
        status: { type: "string", description: "Health status value" },
        reason: {
          type: "string",
          description: "Short explanation (<=200 chars)",
        },
        source: {
          type: "string",
          description: "Reporter name (defaults to self)",
        },
        updates: {
          type: "array",
          description: "Bulk: list of {agent,status,reason?,source?}",
          items: {
            type: "object",
            properties: {
              agent: { type: "string" },
              status: { type: "string" },
              reason: { type: "string" },
              source: { type: "string" },
            },
            required: ["agent", "status"],
          },
        },
      },
    },
  },
  {
    name: "task",
    description:
      "Update this agent's current task for the Activity tab. Call when picking up new work.",
    inputSchema: {
      type: "object" as const,
      properties: {
        task: {
          type: "string",
          description:
            "Short description (<= 200 chars). Include issue refs like #142.",
        },
      },
      required: ["task"],
    },
  },
  {
    name: "orochi_subagents",
    description:
      "Report subagent tree to Orochi Activity tab. Full-replace semantics.",
    inputSchema: {
      type: "object" as const,
      properties: {
        orochi_subagents: {
          type: "array",
          description:
            "Each item: {name, task, status?}. status: running|done|failed.",
          items: {
            type: "object",
            properties: {
              name: { type: "string" },
              task: { type: "string" },
              status: { type: "string" },
            },
            required: ["name", "task"],
          },
        },
      },
      required: ["orochi_subagents"],
    },
  },
  {
    name: "react",
    description: "React to a message with an emoji (toggle semantics).",
    inputSchema: {
      type: "object" as const,
      properties: {
        message_id: {
          type: ["number", "string"],
          description: "The integer ID of the message to react to.",
        },
        emoji: { type: "string", description: "The emoji character." },
      },
      required: ["message_id", "emoji"],
    },
  },
  {
    name: "context",
    description:
      "Get Claude Code context window usage from the screen session statusline.",
    inputSchema: {
      type: "object" as const,
      properties: {
        screen_name: {
          type: "string",
          description: "Screen session name (defaults to agent name).",
        },
      },
    },
  },
  {
    name: "status",
    description: "Get current Orochi connection status and diagnostics.",
    inputSchema: { type: "object" as const, properties: {} },
  },
  {
    name: "subscribe",
    description:
      "Subscribe this agent to an Orochi channel. Persists server-side (ChannelMembership row) so the subscription survives reboot.",
    inputSchema: {
      type: "object" as const,
      properties: {
        channel: {
          type: "string",
          description: "Channel name (e.g. #general).",
        },
      },
      required: ["channel"],
    },
  },
  {
    name: "unsubscribe",
    description:
      "Unsubscribe this agent from an Orochi channel. Removes the persisted ChannelMembership row.",
    inputSchema: {
      type: "object" as const,
      properties: {
        channel: {
          type: "string",
          description: "Channel name (e.g. #general).",
        },
      },
      required: ["channel"],
    },
  },
  {
    name: "channel_info",
    description:
      "Fetch a channel's human-authored description (topic) so the agent understands the channel's purpose. Returns { name, description }.",
    inputSchema: {
      type: "object" as const,
      properties: {
        channel: {
          type: "string",
          description: "Channel name (e.g. #general).",
        },
      },
      required: ["channel"],
    },
  },
  {
    name: "channel_members",
    description:
      "READ-ONLY (#252). List subscribers of an Orochi channel as " +
      "[{name, principal_type: 'human'|'agent', role}]. Uses the " +
      "agent's workspace token (?token=&agent=) — no Django session " +
      "needed; works from MCP sidecars on the bare domain. Pass the " +
      "channel name (e.g. '#general') and optionally workspace=<slug>.",
    inputSchema: {
      type: "object" as const,
      properties: {
        channel: {
          type: "string",
          description: "Channel name (e.g. #general).",
        },
        workspace: {
          type: "string",
          description:
            "Workspace slug. Defaults to env SCITEX_OROCHI_WORKSPACE if set.",
        },
      },
      required: ["channel"],
    },
  },
  {
    name: "my_subscriptions",
    description:
      "READ-ONLY (#253). Return the channels this agent is subscribed " +
      "to as [{channel, joined_at, role}]. Uses the agent's workspace " +
      "token (?token=&agent=) — no Django session needed. Implicitly " +
      "scoped to the calling agent (no target_agent arg); a separate " +
      "write tool will follow in #262 for fleet self-pruning.",
    inputSchema: {
      type: "object" as const,
      properties: {
        workspace: {
          type: "string",
          description:
            "Workspace slug. Defaults to env SCITEX_OROCHI_WORKSPACE if set.",
        },
      },
    },
  },
  {
    name: "download_media",
    description:
      "Download a file from the Orochi hub to local disk. Use this to view screenshots or files posted in chat.",
    inputSchema: {
      type: "object" as const,
      properties: {
        url: {
          type: "string",
          description:
            "The media URL from the Orochi chat (absolute or relative to hub).",
        },
        output_path: {
          type: "string",
          description:
            "Optional: local path to save the file. Defaults to /tmp/orochi-media/<filename>.",
        },
      },
      required: ["url"],
    },
  },
  {
    name: "upload_media",
    description:
      "Upload a local file to the Orochi hub. Returns the URL of the uploaded file.",
    inputSchema: {
      type: "object" as const,
      properties: {
        file_path: {
          type: "string",
          description: "Absolute local path of the file to upload.",
        },
        channel: {
          type: "string",
          description:
            "Channel to associate the upload with (default: #general).",
        },
      },
      required: ["file_path"],
    },
  },
  {
    name: "rsync_media",
    description:
      "Transfer a large file (>10MB) between fleet hosts via background rsync over the SSH mesh. Returns a job_id immediately; use rsync_status to query progress. On completion, posts a message to the specified channel.",
    inputSchema: {
      type: "object" as const,
      properties: {
        src_path: {
          type: "string",
          description:
            "Absolute path on the local host (source file or directory).",
        },
        dst_host: {
          type: "string",
          description:
            "Destination SSH orochi_hostname. One of: mba, nas, ywata-note-win, spartan.",
        },
        dst_path: {
          type: "string",
          description:
            "Absolute destination path on dst_host (e.g. ~/orochi-inbox/ or ~/archives/foo/).",
        },
        channel: {
          type: "string",
          description:
            "Orochi channel to post progress/completion messages (default: #agent).",
        },
      },
      required: ["src_path", "dst_host", "dst_path"],
    },
  },
  {
    name: "rsync_status",
    description: "Query the status of a background rsync transfer job.",
    inputSchema: {
      type: "object" as const,
      properties: {
        job_id: {
          type: "string",
          description: "The job ID returned by rsync_media.",
        },
      },
      required: ["job_id"],
    },
  },
  {
    name: "dm_list",
    description:
      "List 1:1 direct-message channels the current agent participates in (todo#60). Returns rows with name, kind, other_participants, last_message_ts. Read-only — does not send messages.",
    inputSchema: {
      type: "object" as const,
      properties: {
        workspace: {
          type: "string",
          description:
            "Workspace slug. Defaults to env SCITEX_OROCHI_WORKSPACE if set.",
        },
      },
    },
  },
  {
    name: "dm_open",
    description:
      "Get-or-create a 1:1 DM channel between the caller and `recipient` (todo#60). Recipient is a principal key like 'agent:mamba-healer-mba' or 'human:ywatanabe'. Returns the DM row {name, kind, other_participants, ...}; the caller must use the existing `reply` tool with chat_id=<returned name> to actually send a message (the WS reply path is the sole agent write path per spec v3.1 §4.1).",
    inputSchema: {
      type: "object" as const,
      properties: {
        recipient: {
          type: "string",
          description:
            "Principal key: 'agent:<name>' or 'human:<username>'. Alias: peer.",
        },
        peer: {
          type: "string",
          description: "Alias for recipient.",
        },
        workspace: {
          type: "string",
          description:
            "Workspace slug. Defaults to env SCITEX_OROCHI_WORKSPACE if set.",
        },
      },
    },
  },
  {
    name: "connectivity_matrix",
    description:
      "Return the fleet 4×4 reachability matrix as JSON (todo#297 layer 3). Reads connectivity rows produced by the per-host fleet-watch producers (PR B) from $SCITEX_OROCHI_CONNECTIVITY_DIR (default ~/.scitex/orochi/fleet-watch/) and merges them keyed by `from`. Each row is a single host's outbound view: {ts, from, from_hostname, to: {<peer>: {ok, rtt_ms, route, error?}}}. This is a thin read-only aggregator — it does NOT run ssh or measure RTT itself; the per-host producers handle that. Once #298 fleet_report endpoint lands, the same shape will be served from the hub DB without consumer changes.",
    inputSchema: {
      type: "object" as const,
      properties: {},
    },
  },
  {
    name: "sidecar_status",
    description:
      "Return the orochi-side sidecar PID registry as JSON (todo#287 Slice A). Surfaces (a) the running scitex-orochi MCP server (this bun process: orochi_pid, orochi_ppid, orochi_started_at, uptime_seconds, orochi_runtime, agent name) and (b) the rsync_media child-process registry (each rsync job's orochi_pid, status, paths, timestamps). Layer 3 of the 3-layer fleet PID orochi_model — Claude/tmux are owned by scitex-agent-container, container daemons by container snapshot, comms sidecars by orochi (this tool). Read-only; does not spawn or mutate anything.",
    inputSchema: {
      type: "object" as const,
      properties: {},
    },
  },
  {
    name: "self_command",
    description:
      "Send an arbitrary slash command (e.g. /compact, /clear) to the agent's own screen/tmux session. Returns immediately; the command fires after delay_ms when the agent is idle at its prompt. Destructive commands (/clear, /kill, /exit, /quit) require confirm=true.",
    inputSchema: {
      type: "object" as const,
      properties: {
        command: {
          type: "string",
          description:
            "Slash command text to send, starting with '/'. May include args, e.g. '/compact' or '/orochi_model sonnet'. Must match /^\\/[A-Za-z0-9_-]+( .*)?$/ and must not contain single quotes.",
        },
        delay_ms: {
          type: "number",
          description:
            "Delay in ms before sending the command (default: 6000). todo-manager recommends >=6000ms so the MCP response round-trip completes and the agent is idle at its prompt before keys are stuffed.",
        },
        confirm: {
          type: "boolean",
          description:
            "Required true for destructive commands (/clear, /kill, /exit, /quit). Ignored for non-destructive commands.",
        },
      },
      required: ["command"],
    },
  },
  {
    name: "cron_status",
    description:
      "Fleet-wide cron job status (lead msg#16684 follow-up to PR #346). " +
      "Mirrors the ``GET /api/cron/`` endpoint that powers the Machines " +
      "tab cron panel, exposed via MCP so any agent can observe daemon " +
      "state without scraping the dashboard. Returns " +
      '``{"hosts": {<orochi_machine>: {agent, last_heartbeat_at, stale, ' +
      "jobs}}}``. Optional ``host`` arg filters to a single host " +
      "server-side. Workspace-scoped via the MCP sidecar's token; " +
      "read-only.",
    inputSchema: {
      type: "object" as const,
      properties: {
        host: {
          type: "string",
          description:
            "Optional host key (e.g. 'mba', 'nas'). When omitted, all " +
            "hosts in the workspace are returned.",
        },
      },
    },
  },
  {
    name: "export_channel",
    description:
      "Export chat channel messages as JSON, Markdown, or plain text with date slicing. Returns the export content as a string.",
    inputSchema: {
      type: "object" as const,
      properties: {
        chat_id: {
          type: "string",
          description: "Channel to export (e.g. #general, #ywatanabe).",
        },
        format: {
          type: "string",
          description:
            "Output format: json (NDJSON), md (Markdown), txt (plain text). Default: txt.",
        },
        from: {
          type: "string",
          description:
            "Start date (ISO8601 or YYYY-MM-DD). Default: beginning of channel.",
        },
        to: {
          type: "string",
          description: "End date (ISO8601 or YYYY-MM-DD). Default: now.",
        },
      },
      required: ["chat_id"],
    },
  },
  {
    name: "a2a_call",
    description:
      "Call a peer agent via the A2A protocol SDK 1.x (POST JSON-RPC to " +
      "https://a2a.scitex.ai/v1/agents/<agent>). Bearer token is read from " +
      "disk by the MCP server; never enters the agent transcript. Sends " +
      "'A2A-Version: 1.0' header. Default method is 'SendMessage' (unary). " +
      "Other gRPC-style methods: 'GetTask', 'CancelTask'. For SSE streaming " +
      "use the dedicated 'a2a_send_streaming' tool.",
    inputSchema: {
      type: "object" as const,
      properties: {
        agent: {
          type: "string",
          description:
            "Target agent id (e.g. 'lead', 'mgr-scitex', 'head-mba').",
        },
        method: {
          type: "string",
          description:
            "JSON-RPC method. Default: 'SendMessage'. Also: 'GetTask', " +
            "'CancelTask', 'SendStreamingMessage'.",
        },
        text: {
          type: "string",
          description:
            "Convenience for SendMessage / SendStreamingMessage: wrapped " +
            "as params.message.parts[0].text. Ignored if 'params' is set.",
        },
        task_id: {
          type: "string",
          description:
            "Task id for GetTask / CancelTask. Mapped to proto 'id' " +
            "field. Ignored if 'params' is set.",
        },
        message_id: {
          type: "string",
          description:
            "Optional proto message_id (snake_case). Auto-generated if " +
            "omitted. Ignored if 'params' is set.",
        },
        params: {
          type: "object",
          description:
            "Raw JSON-RPC params. Overrides text/task_id if provided. " +
            "Use for advanced calls.",
        },
      },
      required: ["agent"],
    },
  },
  {
    name: "a2a_send_streaming",
    description:
      "Call a peer agent via A2A 'SendStreamingMessage' (SDK 1.x SSE). " +
      "Collects all server-sent events into a single MCP tool result " +
      "({events:[...], count:N}). Use for long-running peer work where " +
      "you want progress events; use 'a2a_call' for short unary calls. " +
      "LIMITATION: the MCP SDK does not yet expose incremental tool " +
      "output, so all events are buffered until the stream ends.",
    inputSchema: {
      type: "object" as const,
      properties: {
        agent: { type: "string", description: "Target agent name." },
        text: {
          type: "string",
          description: "Message text to stream to the peer agent.",
        },
        message_id: {
          type: "string",
          description:
            "Optional proto message_id; auto-generated if omitted.",
        },
      },
      required: ["agent", "text"],
    },
  },
  {
    name: "a2a_get_task",
    description:
      "Poll a long-running A2A task by id (SDK 1.x 'GetTask'). Use after " +
      "'SendMessage' / 'SendStreamingMessage' returns a task id when you " +
      "want to check progress without holding an SSE stream open.",
    inputSchema: {
      type: "object" as const,
      properties: {
        agent: {
          type: "string",
          description:
            "Target agent name (must match the agent that owns the task).",
        },
        task_id: {
          type: "string",
          description:
            "Task id returned by a previous SendMessage/SendStreamingMessage.",
        },
      },
      required: ["agent", "task_id"],
    },
  },
  {
    name: "a2a_cancel_task",
    description:
      "Interrupt a running A2A task (SDK 1.x 'CancelTask'). Returns the " +
      "SDK envelope so the caller can confirm the new task state " +
      "(typically CANCELED).",
    inputSchema: {
      type: "object" as const,
      properties: {
        agent: { type: "string", description: "Target agent name." },
        task_id: { type: "string", description: "Task id to cancel." },
      },
      required: ["agent", "task_id"],
    },
  },
  {
    name: "a2a_list_agents",
    description:
      "Enumerate callable agents in the orochi fleet by hitting the hub's " +
      "registry endpoint (GET /api/agents/). Use this before 'a2a_call' " +
      "so you do not have to guess agent names. Override the URL with " +
      "SCITEX_OROCHI_AGENTS_LIST_URL.",
    inputSchema: {
      type: "object" as const,
      properties: {},
    },
  },
];
