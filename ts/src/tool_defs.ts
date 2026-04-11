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
];
