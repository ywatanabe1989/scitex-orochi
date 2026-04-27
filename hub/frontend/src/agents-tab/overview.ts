// @ts-nocheck
import { getResolvedAgentColor, getSenderIcon } from "../agent-icons";
import {
  _bindSubTabBar,
  _renderAgentContent,
  _renderSubTabBar,
} from "./controls";
import { renderPaneStateBadge } from "./lamps";
import { formatUptime, livenessColor } from "./state";
import {
  apiUrl,
  cleanAgentName,
  escapeHtml,
  isAgentInactive,
  relativeAge,
  timeAgo,
} from "../app/utils";
import { activeTab } from "../tabs";

/* Agents Tab — overview table, registry row builder, context/skills
 * badges, refresh loop, purge action.
 * Loaded last: defines _buildOverviewHtml (used by controls.js
 * _renderAgentContent), renderAgentsTab (the public entry point used
 * by tabs.js), and kicks off startAgentsTabRefresh(). */

/* ── Overview HTML builder (extracted from renderAgentsTab) ─────────── */
export function _buildOverviewHtml(agents) {
  var machineMap = {};
  agents.forEach(function (a) {
    var m = a.machine || "unknown";
    if (!machineMap[m]) machineMap[m] = [];
    machineMap[m].push(a);
  });
  var onlineCount = agents.filter(function (a) {
    return !isAgentInactive(a);
  }).length;
  var offlineCount = agents.length - onlineCount;
  var purgeBtn =
    offlineCount > 0
      ? ' <button class="purge-btn" onclick="purgeStaleAgents()" title="Remove all offline agents">Purge offline (' +
        offlineCount +
        ")</button>"
      : "";
  var summaryHtml =
    '<div class="agents-summary">' +
    '<span class="agents-count">' +
    onlineCount +
    " online, " +
    offlineCount +
    " offline across " +
    Object.keys(machineMap).length +
    " machine(s)" +
    "</span>" +
    purgeBtn +
    Object.keys(machineMap)
      .map(function (m) {
        var online = machineMap[m].filter(function (a) {
          return a.status === "online";
        }).length;
        var total = machineMap[m].length;
        var cls =
          online === total
            ? "machine-ok"
            : online > 0
              ? "machine-warn"
              : "machine-off";
        return (
          '<span class="machine-badge ' +
          cls +
          '">' +
          escapeHtml(m) +
          " (" +
          online +
          "/" +
          total +
          ")</span>"
        );
      })
      .join("") +
    "</div>";
  var tableHtml =
    '<table class="agents-registry-table">' +
    "<thead><tr>" +
    "<th>Star</th><th></th><th>Icon</th><th>Status</th><th>Agent ID</th>" +
    "<th>Role</th><th>Host / Machine</th><th>Model</th><th>Mux</th>" +
    "<th>Ctx</th><th>Skills</th><th>PID</th><th>Channels</th>" +
    "<th>Project</th><th>Workdir</th><th>Pane</th><th>Task</th><th>Subagents</th>" +
    "<th>Config</th><th>Uptime</th><th>Last Activity</th><th>Last Seen</th>" +
    "</tr></thead><tbody>" +
    agents.map(buildAgentRow).join("") +
    "</tbody></table>";
  return summaryHtml + tableHtml;
}

/* ── Main render entry point ────────────────────────────────────────── */
export async function renderAgentsTab() {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var grid = document.getElementById("agents-grid");
  try {
    var res = await fetch(apiUrl("/api/agents/registry"));
    var agents = await res.json();

    if (agents.length === 0) {
      grid.innerHTML = '<p class="empty-notice">No agents connected</p>';
      (globalThis as any)._lastAgentsData = [];
      return;
    }

    /* Sort: online first, then offline */
    agents.sort(function (a, b) {
      var aOff = isAgentInactive(a) ? 1 : 0;
      var bOff = isAgentInactive(b) ? 1 : 0;
      return aOff - bOff || a.name.localeCompare(b.name);
    });
    (globalThis as any)._lastAgentsData = agents;

    /* If selected tab no longer exists (agent departed), revert to overview */
    if (
      (globalThis as any)._selectedAgentTab !== "overview" &&
      !agents.find(function (a) {
        return a.name === (globalThis as any)._selectedAgentTab;
      })
    ) {
      (globalThis as any)._selectedAgentTab = "overview";
    }

    /* Check if sub-tab bar already exists (preserve scroll position) */
    var existingBar = grid.querySelector("#agent-subtab-bar");
    if (!existingBar) {
      /* First render — build full layout */
      grid.innerHTML =
        _renderSubTabBar(agents) +
        '<div id="agent-tab-content" class="agent-tab-content"></div>';
      _bindSubTabBar(grid);
    } else {
      /* Update tab bar labels/active state without destroying it */
      var newBar = document.createElement("div");
      newBar.innerHTML = _renderSubTabBar(agents);
      var updatedBar = newBar.firstChild;
      existingBar.parentNode.replaceChild(updatedBar, existingBar);
      _bindSubTabBar(grid);
    }

    _renderAgentContent(grid);
  } catch (e) {
    console.error("Agents tab error:", e);
  }
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
}

export function buildAgentRow(a) {
  var inactive = isAgentInactive(a);
  var color = getResolvedAgentColor(a.name);
  var liveness = a.liveness || (inactive ? "offline" : "online");
  var statusColor = livenessColor(liveness);
  var statusLabel = liveness;
  var agentIcon = getSenderIcon(a.name, true, 24);
  var dotHtml =
    '<span class="status-dot-inline" style="background:' +
    statusColor +
    '"></span>' +
    '<span class="status-label" style="color:' +
    statusColor +
    '">' +
    statusLabel +
    "</span>";
  /* Filter out `dm:` channels — DM is always implicitly available
   * between any two agents/users, so listing per-agent DM subscriptions
   * adds clutter without information value (ywatanabe 2026-04-27). */
  var uniqueChannels = [...new Set(a.channels || [])].filter(function (c) {
    return typeof c === "string" && c.indexOf("dm:") !== 0;
  });
  var channelsHtml = uniqueChannels
    .map(function (c) {
      return '<span class="ch-badge">' + escapeHtml(c) + "</span>";
    })
    .join("");
  /* Star (pinned-to-top) — replaces the earlier pin terminology
   * site-wide. ywatanabe 2026-04-19: "we do not use pin at all; just
   * use star". Glyph: ★ filled for starred, ☆ outline otherwise.
   * data-pin-name / pin-btn / togglePinAgent retain their names for
   * backend/registry stability; the USER-FACING label is Star. */
  var pinIcon = a.pinned ? "\u2605" : "\u2606";
  var pinTitle = a.pinned ? "Unstar" : "Star";
  var pinBtnHtml =
    '<button class="pin-btn star-btn' +
    (a.pinned ? " pinned starred" : "") +
    '" data-pin-name="' +
    escapeHtml(a.name) +
    '" title="' +
    pinTitle +
    '" onclick="event.stopPropagation();togglePinAgent(\'' +
    escapeHtml(a.name).replace(/'/g, "\\'") +
    "', " +
    !a.pinned +
    ')">' +
    pinIcon +
    "</button>";
  var rowClass =
    "agent-row" +
    (inactive ? " agent-inactive" : "") +
    (a.pinned && inactive ? " pinned-offline" : "");
  return (
    '<tr class="' +
    rowClass +
    '" data-agent-name="' +
    escapeHtml(a.name) +
    '">' +
    "<td>" +
    pinBtnHtml +
    "</td>" +
    '<td><button class="kill-btn" data-kill-name="' +
    escapeHtml(a.name) +
    '" title="Kill agent" onclick="event.stopPropagation();killAgent(\'' +
    escapeHtml(a.name).replace(/'/g, "\\'") +
    "', this)\">\u2715</button>" +
    '<button class="restart-btn" data-restart-name="' +
    escapeHtml(a.name) +
    '" title="Restart agent" onclick="event.stopPropagation();restartAgent(\'' +
    escapeHtml(a.name).replace(/'/g, "\\'") +
    "', this)\">\u21BB</button></td>" +
    '<td class="agent-icon-cell avatar-clickable" data-avatar-agent="' +
    escapeHtml(a.name) +
    '" title="Click to change avatar" onclick="event.stopPropagation();openAvatarPicker(\'' +
    escapeHtml(a.name).replace(/'/g, "\\'") +
    "')\">" +
    agentIcon +
    "</td>" +
    "<td>" +
    dotHtml +
    "</td>" +
    '<td class="agent-id-cell">' +
    escapeHtml(cleanAgentName(a.agent_id || a.name)) +
    "</td>" +
    "<td>" +
    escapeHtml(a.role || "agent") +
    "</td>" +
    '<td class="monospace-cell">' +
    escapeHtml(a.machine || "unknown") +
    "</td>" +
    '<td class="muted-cell">' +
    escapeHtml(a.model || "-") +
    "</td>" +
    '<td class="muted-cell">' +
    escapeHtml(a.multiplexer || "-") +
    "</td>" +
    '<td class="ctx-cell">' +
    renderContextBadge(a.orochi_context_pct, a.context_management) +
    "</td>" +
    '<td class="skills-cell">' +
    renderSkillsBadge(a.orochi_skills_loaded) +
    "</td>" +
    '<td class="pid-cell muted-cell">' +
    (a.pid ? String(a.pid) : "-") +
    "</td>" +
    '<td class="small-cell">' +
    channelsHtml +
    "</td>" +
    '<td class="muted-cell">' +
    escapeHtml(a.project || "-") +
    "</td>" +
    '<td class="monospace-cell small-cell" title="' +
    escapeHtml(a.workdir || "") +
    '">' +
    escapeHtml(a.workdir ? a.workdir.replace(/^\/home\/[^/]+/, "~") : "-") +
    "</td>" +
    '<td class="pane-state-cell">' +
    renderPaneStateBadge(a.orochi_pane_state, a.orochi_stuck_prompt_text) +
    "</td>" +
    '<td class="task-cell">' +
    escapeHtml(a.orochi_current_task || "-") +
    "</td>" +
    '<td class="small-cell">' +
    (a.subagents && a.subagents.length > 0
      ? a.subagents
          .map(function (s) {
            var sClass =
              s.status === "done" ? "subagent-done" : "subagent-running";
            return (
              '<span class="subagent-badge ' +
              sClass +
              '" title="' +
              escapeHtml(s.task || "") +
              '">' +
              escapeHtml(s.name || "subagent") +
              "</span>"
            );
          })
          .join(" ")
      : a.orochi_subagent_count && a.orochi_subagent_count > 0
        ? '<span class="subagent-badge subagent-running" title="' +
          a.orochi_subagent_count +
          ' subagent(s)">\uD83D\uDD27 ' +
          a.orochi_subagent_count +
          "</span>"
        : '<span class="muted-cell">-</span>') +
    "</td>" +
    "<td>" +
    (a.orochi_claude_md
      ? '<button class="claude-md-btn" onclick="event.stopPropagation();toggleClaudeMd(this)" title="View CLAUDE.md">CLAUDE.md</button>'
      : '<span class="muted-cell">-</span>') +
    "</td>" +
    '<td class="muted-cell" title="Registered: ' +
    escapeHtml(a.registered_at || "") +
    '">' +
    formatUptime(a.registered_at) +
    "</td>" +
    '<td class="muted-cell" title="' +
    escapeHtml(a.last_action || "") +
    '">' +
    (a.idle_seconds != null
      ? '<span class="idle-badge idle-' +
        liveness +
        '">' +
        formatUptime(a.last_action) +
        " ago</span>"
      : timeAgo(a.last_action)) +
    "</td>" +
    '<td class="muted-cell" title="' +
    escapeHtml(a.last_heartbeat || "") +
    '">' +
    (typeof relativeAge === "function"
      ? relativeAge(a.last_heartbeat)
      : timeAgo(a.last_heartbeat)) +
    "</td>" +
    "</tr>" +
    (function () {
      var raw = a.orochi_pane_tail_block || a.orochi_pane_tail || "";
      if (!raw) return "";
      var lines = String(raw).split(/\r?\n/);
      var tail = lines.slice(-10).join("\n");
      return (
        '<tr class="agent-pane-row"><td colspan="22">' +
        '<pre class="agent-pane-preview" title="Last 10 lines of ' +
        escapeHtml(a.name) +
        ' tmux pane">' +
        escapeHtml(tail) +
        "</pre></td></tr>"
      );
    })() +
    (a.orochi_claude_md
      ? '<tr class="claude-md-detail" style="display:none"><td colspan="22"><pre class="claude-md-content">' +
        escapeHtml(a.orochi_claude_md) +
        "</pre></td></tr>"
      : "")
  );
}

/* Toggle CLAUDE.md detail row visibility */
export function toggleClaudeMd(btn) {
  var row = btn.closest("tr");
  var detailRow = row.nextElementSibling;
  if (detailRow && detailRow.classList.contains("claude-md-detail")) {
    var visible = detailRow.style.display !== "none";
    detailRow.style.display = visible ? "none" : "table-row";
    btn.textContent = visible ? "CLAUDE.md" : "Hide";
  }
}

export function renderContextBadge(pct, cm) {
  if (pct == null) return renderCompactPolicySuffix("-", cm);
  var n = Number(pct);
  if (isNaN(n)) return renderCompactPolicySuffix("-", cm);
  // Color thresholds bias on the YAML-declared trigger when present so an
  // agent configured to compact at 60% turns red sooner than the default 80.
  var trigger =
    cm && cm.trigger_at_percent != null ? Number(cm.trigger_at_percent) : 80;
  var warn = Math.max(10, trigger - 20);
  var color;
  if (n < warn) color = "#4ecdc4";
  else if (n < trigger) color = "#ffd93d";
  else color = "#ef4444";
  var title =
    cm && cm.strategy && cm.strategy !== "noop"
      ? "Context window used (auto-" + cm.strategy + " at " + trigger + "%)"
      : "Context window used";
  var badge =
    '<span class="ctx-badge" title="' +
    title +
    '" style="background:' +
    color +
    ";color:#111;padding:1px 6px;" +
    'border-radius:10px;font-size:11px;font-weight:600">ctx ' +
    n.toFixed(1) +
    "%</span>";
  return renderCompactPolicySuffix(badge, cm);
}

// Append a small "/<trigger>%" suffix when the agent has a compact/restart
// policy declared in YAML, so operators can see the threshold at a glance.
export function renderCompactPolicySuffix(badge, cm) {
  if (!cm || !cm.strategy || cm.strategy === "noop") return badge;
  var trig = cm.trigger_at_percent;
  if (trig == null) return badge;
  var glyph = cm.strategy === "restart" ? "↻" : "↺";
  return (
    badge +
    ' <span class="ctx-policy" title="auto-' +
    cm.strategy +
    " at " +
    trig +
    '%" style="color:#888;font-size:10px;margin-left:2px">' +
    glyph +
    Number(trig).toFixed(0) +
    "%</span>"
  );
}

export function renderSkillsBadge(skills) {
  if (!skills || !skills.length) return '<span class="muted-cell">-</span>';
  var tip = skills
    .map(function (s) {
      return String(s);
    })
    .join("\n");
  return (
    '<span class="skills-badge" title="' +
    escapeHtml(tip) +
    '" ' +
    'style="background:#2a3340;color:#9ecbff;padding:1px 6px;' +
    'border-radius:10px;font-size:11px">skills:' +
    skills.length +
    "</span>"
  );
}

/* Auto-refresh: 3s when a per-agent tab is active, 1s for overview */
export function startAgentsTabRefresh() {
  stopAgentsTabRefresh();
  (globalThis as any)._agentsTabInterval = setInterval(function () {
    if (activeTab === "agents-tab") renderAgentsTab();
  }, 3000);
}
export function stopAgentsTabRefresh() {
  if ((globalThis as any)._agentsTabInterval) {
    clearInterval((globalThis as any)._agentsTabInterval);
    (globalThis as any)._agentsTabInterval = null;
  }
}

export async function purgeStaleAgents() {
  try {
    var token = window.__orochiCsrfToken || "";
    var headers = { "Content-Type": "application/json" };
    if (token) headers["X-CSRFToken"] = token;
    var res = await fetch(apiUrl("/api/agents/purge/"), {
      method: "POST",
      headers: headers,
      credentials: "same-origin",
    });
    if (res.ok) {
      renderAgentsTab();
    } else {
      console.error("Purge failed:", res.status);
    }
  } catch (e) {
    console.error("Purge error:", e);
  }
}

startAgentsTabRefresh();
