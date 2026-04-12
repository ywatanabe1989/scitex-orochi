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
    name: "subagents",
    description:
      "Report subagent tree to Orochi Activity tab. Full-replace semantics.",
    inputSchema: {
      type: "object" as const,
      properties: {
        subagents: {
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
      required: ["subagents"],
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
    name: "self_command",
    description:
      "Send an arbitrary slash command (e.g. /compact, /clear) to the agent's own screen/tmux session. Returns immediately; the command fires after delay_ms when the agent is idle at its prompt. Destructive commands (/clear, /kill, /exit, /quit) require confirm=true.",
    inputSchema: {
      type: "object" as const,
      properties: {
        command: {
          type: "string",
          description:
            "Slash command text to send, starting with '/'. May include args, e.g. '/compact' or '/model sonnet'. Must match /^\\/[A-Za-z0-9_-]+( .*)?$/ and must not contain single quotes.",
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
    name: "dm_send",
    description:
      "Send a direct message (DM) to another principal (agent or user). The hub canonicalises the DM channel name as #dm-{lo}__{hi} from the sorted, lower-cased participant names — you cannot impersonate DMs you are not part of. Equivalent to reply(chat_id='#dm-...') once the channel exists, but this tool does the canonicalisation for you.",
    inputSchema: {
      type: "object" as const,
      properties: {
        recipient: {
          type: "string",
          description:
            "The other principal's name (agent name or Django username). Case-insensitive. Leading @ / # are stripped.",
        },
        text: { type: "string", description: "The DM text to send." },
      },
      required: ["recipient", "text"],
    },
  },
];
