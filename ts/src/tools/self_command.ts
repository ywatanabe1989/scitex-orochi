/**
 * Self-command tool: send commands to the agent's own terminal session.
 *
 * Claude Code cannot run /compact, /clear, or exit while it is processing
 * the current request. But this MCP sidecar is a separate bun process, so
 * we schedule the command with setTimeout — by the time it fires, the
 * agent has already received our MCP response and is idle at its prompt.
 *
 * The agent's terminal multiplexer is determined from SCITEX_OROCHI_MULTIPLEXER
 * (screen|tmux); default is "tmux" — set SCITEX_OROCHI_MULTIPLEXER=screen to opt in.
 */
import { exec } from "child_process";
import { OROCHI_AGENT } from "./_shared.js";

// Allow only safe characters in the session name to prevent shell injection.
function validateSessionName(name: string): string | null {
  if (!/^[A-Za-z0-9._-]+$/.test(name)) return null;
  return name;
}

type Multiplexer = "screen" | "tmux";

function getMultiplexer(): Multiplexer {
  const m = (process.env.SCITEX_OROCHI_MULTIPLEXER || "tmux").toLowerCase();
  return m === "screen" ? "screen" : "tmux";
}

/**
 * Build the shell command that sends `text` followed by Enter into the
 * given multiplexer session. `text` should NOT contain shell metacharacters
 * beyond the slash-command payload; it is single-quoted below.
 */
function buildSendKeysCommand(
  mux: Multiplexer,
  session: string,
  text: string,
): string {
  // We single-quote text for the outer shell. Reject any text containing
  // a single quote to keep escaping trivial and injection-proof.
  if (text.includes("'")) {
    throw new Error("self-command text must not contain single quotes");
  }
  if (mux === "tmux") {
    // `tmux send-keys -l` sends literal then we send Enter separately.
    return `tmux send-keys -t '${session}' '${text}' Enter`;
  }
  // GNU screen: use `stuff` with a literal newline (\r = carriage return).
  return `screen -S '${session}' -X stuff $'${text}\\r'`;
}

function scheduleSelfCommand(
  text: string,
  delayMs: number,
  label: string,
): { content: Array<{ type: string; text: string }> } {
  const rawSession = OROCHI_AGENT;
  if (!rawSession) {
    return {
      content: [
        { type: "text", text: "ERROR: SCITEX_OROCHI_AGENT env var not set" },
      ],
    };
  }
  const session = validateSessionName(rawSession);
  if (!session) {
    return {
      content: [
        {
          type: "text",
          text: `ERROR: SCITEX_OROCHI_AGENT contains unsafe characters: ${rawSession}`,
        },
      ],
    };
  }

  const mux = getMultiplexer();
  let cmd: string;
  try {
    cmd = buildSendKeysCommand(mux, session, text);
  } catch (err) {
    return {
      content: [{ type: "text", text: `ERROR: ${(err as Error).message}` }],
    };
  }

  const delay = Math.max(0, delayMs);
  setTimeout(() => {
    exec(cmd, (err) => {
      if (err) {
        console.error(
          `[orochi] ${label} failed for session '${session}' (${mux}): ${err.message}`,
        );
      } else {
        console.error(
          `[orochi] ${label} sent '${text}' to ${mux} session '${session}'`,
        );
      }
    });
  }, delay);

  return {
    content: [
      {
        type: "text",
        text: `${label} scheduled in ${delay}ms for ${mux} session '${session}'`,
      },
    ],
  };
}

// Destructive slash commands require confirm=true.
const DESTRUCTIVE_COMMANDS = new Set(["/clear", "/kill", "/exit", "/quit"]);

// Allowlist of slash commands safe to inject via self_command.
// Modal-opening commands (/model, /agents, /permissions, /login, /config, ...)
// trap the agent in a selector dialog and require external Escape rescue, so
// they are NOT on this list. Free-text prompts (no leading '/') bypass this
// gate entirely — they just land as prompt text.
const SELF_COMMAND_ALLOWLIST: readonly string[] = [
  "/compact",
  "/clear",
  "/cost",
  "/help",
  "/status",
] as const;

// Returns true if `cmd` is safe to send via self_command.
// Free-text (no leading '/') is always safe. Slash commands are safe only if
// their first whitespace-delimited token is in SELF_COMMAND_ALLOWLIST.
export function isSafeForSelfCommand(cmd: string): boolean {
  const trimmed = (cmd || "").trim();
  if (!trimmed.startsWith("/")) {
    return true;
  }
  const slashName = trimmed.split(/\s+/, 1)[0];
  return SELF_COMMAND_ALLOWLIST.includes(slashName);
}

// Validate slash-command text. Returns error string on failure, null on OK.
function validateSelfCommand(command: string): string | null {
  if (!command || typeof command !== "string") {
    return "command is required";
  }
  // Free-text (no leading '/') is allowed — it lands as prompt text.
  if (!command.startsWith("/")) {
    if (command.includes("'")) {
      return "command must not contain single quotes (shell injection guard)";
    }
    return null;
  }
  if (command.includes("'")) {
    return "command must not contain single quotes (shell injection guard)";
  }
  if (!/^\/[A-Za-z0-9_-]+( .*)?$/.test(command)) {
    return "command must match /^\\/[A-Za-z0-9_-]+( .*)?$/";
  }
  return null;
}

export async function handleSelfCommand(args: {
  command?: string;
  delay_ms?: number;
  confirm?: boolean;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  const command = (args?.command || "").trim();
  const err = validateSelfCommand(command);
  if (err) {
    return { content: [{ type: "text", text: `ERROR: ${err}` }] };
  }

  // Allowlist gate: reject modal-opening slash commands before scheduling.
  if (!isSafeForSelfCommand(command)) {
    const rejected = command.split(/\s+/, 1)[0];
    return {
      content: [
        {
          type: "text",
          text:
            `ERROR: slash command '${rejected}' is not in self_command allowlist. ` +
            `Safe commands: ${SELF_COMMAND_ALLOWLIST.join(", ")}. ` +
            `Modal-opening commands like /model, /agents, /permissions trap the agent and are blocked. ` +
            `Free-text prompts (no leading slash) are always allowed.`,
        },
      ],
    };
  }

  // Extract the bare slash name (no args) for destructive-list lookup.
  const slashName = command.split(/\s+/, 1)[0];
  if (DESTRUCTIVE_COMMANDS.has(slashName) && !args?.confirm) {
    return {
      content: [
        {
          type: "text",
          text: `ERROR: '${slashName}' is destructive; pass confirm=true to fire`,
        },
      ],
    };
  }

  const delay = args?.delay_ms ?? 6000;
  return scheduleSelfCommand(command, delay, `self_command(${slashName})`);
}
