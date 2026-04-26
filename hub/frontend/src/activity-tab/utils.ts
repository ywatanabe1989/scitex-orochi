// @ts-nocheck
import { escapeHtml } from "../app/utils";

/* activity-tab/utils.js — generic helpers for the Agents UI.
 * Pure functions: strip ANSI, formatters, liveness labels/order,
 * task parse, computeAgentState, health + issue linkify, isDeadAgent. */

/* Strip ANSI escape sequences for clean terminal display */
export function _stripAnsi(str) {
  return str
    .replace(/\x1B\[[0-9;]*[A-Za-z]/g, "")
    .replace(/\x1B\][^\x07\x1B]*(?:\x07|\x1B\\)/g, "")
    .replace(/\x1B[@-_][0-?]*[ -/]*[@-~]/g, "")
    .replace(/\r/g, "");
}

export function _formatIdle(seconds) {
  if (seconds == null) return "";
  if (seconds < 60) return seconds + "s";
  if (seconds < 3600) return Math.floor(seconds / 60) + "m";
  return Math.floor(seconds / 3600) + "h";
}

/* Compute seconds since an ISO timestamp. Returns null if unparseable. */
export function _secondsSinceIso(iso) {
  if (!iso) return null;
  var t = Date.parse(iso);
  if (isNaN(t)) return null;
  return Math.max(0, Math.floor((Date.now() - t) / 1000));
}

/* Format a duration in seconds as "up 3h 14m" style. */
export function _formatUptime(seconds) {
  if (seconds == null) return "";
  var h = Math.floor(seconds / 3600);
  var m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return "up " + h + "h " + m + "m";
  if (m > 0) return "up " + m + "m";
  return "up " + seconds + "s";
}

/* Split a current_task string like "Bash: docker compose build" into
 * a tool name + argument preview. Returns {tool, arg, isProse}. If no
 * colon separator is found we treat the whole string as prose (e.g. a
 * last_user_msg snippet, not a tool call). */
export function _parseCurrentTask(task) {
  if (!task) return { tool: "", arg: "", isProse: false };
  var idx = task.indexOf(": ");
  if (idx > 0 && idx < 40) {
    var tool = task.slice(0, idx);
    /* Heuristic: tool names are short alnum/underscore (incl. mcp__ prefix) */
    if (/^[A-Za-z_][A-Za-z0-9_]{0,60}$/.test(tool)) {
      return { tool: tool, arg: task.slice(idx + 2), isProse: false };
    }
  }
  /* Pure tool name with no argument (e.g. "Bash") */
  if (/^[A-Za-z_][A-Za-z0-9_]{0,60}$/.test(task)) {
    return { tool: task, arg: "", isProse: false };
  }
  return { tool: "", arg: task, isProse: true };
}

export function _livenessLabel(liveness) {
  switch (liveness) {
    case "online":
      return "active";
    case "idle":
      return "idle";
    case "stale":
      return "stale";
    case "offline":
      return "offline";
    default:
      return liveness || "unknown";
  }
}

export function _livenessOrder(liveness) {
  /* Sort: stale first (needs attention), then online, idle, offline */
  switch (liveness) {
    case "stale":
      return 0;
    case "online":
      return 1;
    case "idle":
      return 2;
    case "offline":
      return 3;
    default:
      return 4;
  }
}

export function _renderHealthField(health) {
  if (!health || !health.status) return "";
  var st = String(health.status);
  var reason = health.reason ? " · " + escapeHtml(health.reason) : "";
  var src = health.source ? " (" + escapeHtml(health.source) + ")" : "";
  return (
    '<div class="activity-health activity-health-' +
    escapeHtml(st) +
    '">' +
    '<span class="activity-health-icon">\uD83E\uDE7A</span> ' +
    '<span class="activity-health-status">' +
    escapeHtml(st) +
    "</span>" +
    reason +
    src +
    "</div>"
  );
}

/* Linkify #NNN issue refs in an already-escaped HTML string */
export function _linkifyIssues(safeHtml) {
  return safeHtml.replace(
    /#(\d+)\b/g,
    '<a class="issue-link" href="https://github.com/ywatanabe1989/scitex-orochi/issues/$1" target="_blank">#$1</a>',
  );
}

/* Prominent task renderer — this is the card's hero row. `task` is the
 * rich current_task string (e.g. "Bash: docker compose build"). `age`
 * is a pre-formatted age label or empty. `fallback` is last_message_preview
 * used when there is no task at all. */
export function _renderTaskField(task, fallback, age) {
  var ageChip = age
    ? '<span class="activity-task-age" title="seconds since last heartbeat">' +
      escapeHtml(age) +
      "</span>"
    : "";
  if (!task) {
    if (fallback) {
      return (
        '<div class="activity-task-row activity-task-prose">' +
        '<span class="activity-task-fallback" title="last activity (no structured task set)">' +
        _linkifyIssues(escapeHtml(fallback)) +
        "</span>" +
        ageChip +
        "</div>"
      );
    }
    return (
      '<div class="activity-task-row">' +
      '<span class="activity-task-empty">no task reported</span>' +
      ageChip +
      "</div>"
    );
  }
  var parsed = _parseCurrentTask(task);
  var fullTitle = escapeHtml(task);
  if (parsed.isProse) {
    return (
      '<div class="activity-task-row activity-task-prose" title="' +
      fullTitle +
      '">' +
      '<span class="activity-tool-prose">' +
      _linkifyIssues(escapeHtml(parsed.arg)) +
      "</span>" +
      ageChip +
      "</div>"
    );
  }
  var toolHtml = parsed.tool
    ? '<span class="activity-tool-name">' + escapeHtml(parsed.tool) + "</span>"
    : "";
  var argHtml = parsed.arg
    ? '<span class="activity-tool-arg">' +
      _linkifyIssues(escapeHtml(parsed.arg)) +
      "</span>"
    : "";
  return (
    '<div class="activity-task-row activity-task-tool" title="' +
    fullTitle +
    '">' +
    toolHtml +
    argHtml +
    ageChip +
    "</div>"
  );
}

/* Derive a higher-level "what is the agent doing" state, distinct from
 * the WS-level connection status and the heartbeat-age liveness.
 *
 * Precedence (highest wins):
 *   selecting  — pane classifier says agent is blocked on a choice
 *                (y_n_prompt, compose_pending_unsent) or needs a human
 *                (auth_error, mcp_broken)
 *   running    — LLM fired a tool within the last 30s (active work)
 *   idle       — connected, quiet
 *   offline    — WS is disconnected
 */
export function _computeAgentState(a) {
  var pane = a.pane_state || "";
  if (pane === "compacting" || pane === "auto_compact") {
    return "compacting";
  }
  if (
    pane === "y_n_prompt" ||
    pane === "compose_pending_unsent" ||
    pane === "auth_error" ||
    pane === "mcp_broken" ||
    pane === "stuck"
  ) {
    return "selecting";
  }
  var connected = (a.status || "online") !== "offline";
  if (!connected) return "offline";
  /* Heuristic fallback for compact when pane classifier hasn't fired:
   * the last tool name contains "compact" (mcp or slash command). */
  var lastTool = String(a.last_tool_name || "").toLowerCase();
  if (lastTool.indexOf("compact") !== -1) return "compacting";
  var lastToolSec =
    typeof _secondsSinceIso === "function"
      ? _secondsSinceIso(a.last_tool_at || a.last_action)
      : null;
  if (lastToolSec != null && lastToolSec < 30) return "running";
  return "idle";
}

/* Radial topology renderer. Agents sit on an outer ring, channels on
 * an inner ring, with straight-line edges between subscribed pairs.
 * Pure SVG + vanilla JS — no d3, no external deps. Click an agent node
 * to toggle the inline detail panel (same hook the list view uses;
 * re-uses _renderActivityAgentDetail + _fetchActivityDetail so state
 * survives heartbeat-driven re-renders). */
/* Classify an agent's "dead" state.
 *
 * Trusts the classifier's `pane_state` (agent_meta_pkg/_classifier.py)
 * as the authoritative signal. Only `stale` (3+ cycles of unchanged
 * pane content with no busy-animation markers) means "stuck and needs
 * help". `idle` means at-prompt-waiting — a legitimate live state, not
 * dead. Compose/permission/y_n/auth_error states are awaiting input,
 * also not dead.
 *
 * Falls back to the legacy 180s tool/action heuristic only when
 * `pane_state` is missing (e.g. the agent's heartbeat path predates
 * agent_meta classifier output). */
export function _isDeadAgent(a) {
  if (!a) return false;
  var connected = (a.status || "online") !== "offline";
  if (!connected) return false;
  var pane = (a.pane_state || "").toLowerCase();
  if (pane === "stale") return true;
  if (pane) return false;
  var toolSec =
    typeof _secondsSinceIso === "function"
      ? _secondsSinceIso(a.last_tool_at)
      : null;
  var actSec =
    typeof _secondsSinceIso === "function"
      ? _secondsSinceIso(a.last_action)
      : null;
  var noTool = toolSec == null || toolSec > 180;
  var noAct = actSec == null || actSec > 180;
  return noTool && noAct;
}
/* Expose for app.js (sidebar ghost rule) and other modules — single
 * source of truth for "dead agent" across every render surface. */
window._isDeadAgent = _isDeadAgent;
