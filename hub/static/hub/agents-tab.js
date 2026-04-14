/* Agents Tab -- registry table with per-agent sub-tab terminal views */
/* globals: escapeHtml, getAgentColor, isAgentInactive, timeAgo,
   addTag, activeTab, apiUrl */
var _agentsTabInterval = null;
var _selectedAgentTab = "overview"; /* "overview" or agent name */
var _lastAgentsData = [];           /* cached for sub-tab renders */

/* ── Sub-tab bar ────────────────────────────────────────────────────── */
function _renderSubTabBar(agents) {
  var tabs = [{ id: "overview", label: "Overview" }];
  agents.forEach(function (a) {
    tabs.push({ id: a.name, label: a.name });
  });
  var html = '<div class="agent-subtab-bar" id="agent-subtab-bar">';
  tabs.forEach(function (t) {
    var active = t.id === _selectedAgentTab ? " agent-subtab-active" : "";
    var inactive = t.id !== "overview" && isAgentInactive(
      agents.find(function(a){ return a.name === t.id; }) || {}
    ) ? " agent-subtab-offline" : "";
    html +=
      '<button class="agent-subtab' + active + inactive + '" ' +
      'data-subtab="' + escapeHtml(t.id) + '">' +
      escapeHtml(t.label) +
      "</button>";
  });
  html += "</div>";
  return html;
}

function _bindSubTabBar(grid) {
  var bar = grid.querySelector("#agent-subtab-bar");
  if (!bar) return;
  bar.addEventListener("click", function (e) {
    var btn = e.target.closest(".agent-subtab");
    if (!btn) return;
    _selectedAgentTab = btn.getAttribute("data-subtab");
    /* Re-render content area only, not the whole tab (preserve scroll) */
    _renderAgentContent(grid);
  });
}

/* ── Per-agent detail view ──────────────────────────────────────────── */
function _renderAgentDetail(a) {
  var liveness = a.liveness || (isAgentInactive(a) ? "offline" : "online");
  var statusColor = livenessColor(liveness);
  var pane = a.pane_tail_block || a.pane_tail || "";

  var headerHtml =
    '<div class="agent-detail-header">' +
    '<span class="status-dot-inline" style="background:' + statusColor + '"></span>' +
    '<strong>' + escapeHtml(a.name) + '</strong>' +
    ' <span class="agent-detail-meta">' +
    escapeHtml(a.role || "agent") + " · " +
    escapeHtml(a.machine || "?") + " · " +
    escapeHtml(a.model || "-") +
    (a.context_pct != null ? " · ctx " + Number(a.context_pct).toFixed(1) + "%" : "") +
    (a.current_task ? ' · <em>' + escapeHtml(a.current_task) + '</em>' : '') +
    "</span>" +
    "</div>";

  var paneHtml =
    '<div class="agent-detail-pane-wrap">' +
    '<div class="agent-detail-pane-label">Terminal output</div>' +
    '<pre class="agent-detail-pane">' +
    (pane ? escapeHtml(pane) : '<span class="muted-cell">No terminal output available</span>') +
    "</pre>" +
    "</div>";

  var claudeMdHtml = a.claude_md
    ? '<div class="agent-detail-section">' +
      '<div class="agent-detail-pane-label">CLAUDE.md</div>' +
      '<pre class="agent-detail-claude-md">' + escapeHtml(a.claude_md) + "</pre>" +
      "</div>"
    : "";

  var channelsHtml = "";
  if (a.channels && a.channels.length) {
    var unique = [...new Set(a.channels)];
    channelsHtml =
      '<div class="agent-detail-section">' +
      '<span class="agent-detail-pane-label">Channels: </span>' +
      unique.map(function(c){ return '<span class="ch-badge">' + escapeHtml(c) + "</span>"; }).join("") +
      "</div>";
  }

  return (
    '<div class="agent-detail-view">' +
    headerHtml +
    paneHtml +
    channelsHtml +
    claudeMdHtml +
    "</div>"
  );
}

/* Render only the content area (below tab bar) */
function _renderAgentContent(grid) {
  var content = grid.querySelector("#agent-tab-content");
  if (!content) return;

  /* Update active state on tab bar */
  grid.querySelectorAll(".agent-subtab").forEach(function(btn) {
    btn.classList.toggle(
      "agent-subtab-active",
      btn.getAttribute("data-subtab") === _selectedAgentTab
    );
  });

  if (_selectedAgentTab === "overview") {
    content.innerHTML = _buildOverviewHtml(_lastAgentsData);
    /* Re-bind click-to-filter on the newly rendered rows */
    content.querySelectorAll(".agent-row[data-agent-name]").forEach(function(el) {
      el.addEventListener("click", function() {
        addTag("agent", el.getAttribute("data-agent-name"));
      });
    });
    return;
  }

  var agent = _lastAgentsData.find(function(a){ return a.name === _selectedAgentTab; });
  if (!agent) {
    content.innerHTML = '<p class="empty-notice">Agent "' + escapeHtml(_selectedAgentTab) + '" not found.</p>';
    return;
  }
  content.innerHTML = _renderAgentDetail(agent);
  /* Scroll pane to bottom so latest output is visible */
  var pre = content.querySelector(".agent-detail-pane");
  if (pre) pre.scrollTop = pre.scrollHeight;
}

/* ── Overview HTML builder (extracted from renderAgentsTab) ─────────── */
function _buildOverviewHtml(agents) {
  var machineMap = {};
  agents.forEach(function(a) {
    var m = a.machine || "unknown";
    if (!machineMap[m]) machineMap[m] = [];
    machineMap[m].push(a);
  });
  var onlineCount = agents.filter(function(a){ return !isAgentInactive(a); }).length;
  var offlineCount = agents.length - onlineCount;
  var purgeBtn =
    offlineCount > 0
      ? ' <button class="purge-btn" onclick="purgeStaleAgents()" title="Remove all offline agents">Purge offline (' +
        offlineCount + ")</button>"
      : "";
  var summaryHtml =
    '<div class="agents-summary">' +
    '<span class="agents-count">' +
    onlineCount + " online, " + offlineCount + " offline across " +
    Object.keys(machineMap).length + " machine(s)" +
    "</span>" +
    purgeBtn +
    Object.keys(machineMap).map(function(m) {
      var online = machineMap[m].filter(function(a){ return a.status === "online"; }).length;
      var total = machineMap[m].length;
      var cls = online === total ? "machine-ok" : online > 0 ? "machine-warn" : "machine-off";
      return '<span class="machine-badge ' + cls + '">' + escapeHtml(m) + " (" + online + "/" + total + ")</span>";
    }).join("") +
    "</div>";
  var tableHtml =
    '<table class="agents-registry-table">' +
    "<thead><tr>" +
    "<th>Pin</th><th></th><th>Icon</th><th>Status</th><th>Agent ID</th>" +
    "<th>Role</th><th>Host / Machine</th><th>Model</th><th>Mux</th>" +
    "<th>Ctx</th><th>Skills</th><th>PID</th><th>Channels</th>" +
    "<th>Project</th><th>Workdir</th><th>Task</th><th>Subagents</th>" +
    "<th>Config</th><th>Uptime</th><th>Last Activity</th><th>Last Seen</th>" +
    "</tr></thead><tbody>" +
    agents.map(buildAgentRow).join("") +
    "</tbody></table>";
  return summaryHtml + tableHtml;
}

/* ── Main render entry point ────────────────────────────────────────── */
async function renderAgentsTab() {
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
      _lastAgentsData = [];
      return;
    }

    /* Sort: online first, then offline */
    agents.sort(function(a, b) {
      var aOff = isAgentInactive(a) ? 1 : 0;
      var bOff = isAgentInactive(b) ? 1 : 0;
      return aOff - bOff || a.name.localeCompare(b.name);
    });
    _lastAgentsData = agents;

    /* If selected tab no longer exists (agent departed), revert to overview */
    if (_selectedAgentTab !== "overview" &&
        !agents.find(function(a){ return a.name === _selectedAgentTab; })) {
      _selectedAgentTab = "overview";
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
    try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
  }
}

function livenessColor(liveness) {
  switch (liveness) {
    case "online": return "#4ecdc4";
    case "idle": return "#ffd93d";
    case "stale": return "#ff8c42";
    case "offline": return "#ef4444";
    default: return "#888";
  }
}

function formatUptime(isoStr) {
  if (!isoStr) return "-";
  var d = new Date(isoStr);
  if (isNaN(d.getTime())) return "-";
  var sec = Math.floor((Date.now() - d.getTime()) / 1000);
  if (sec < 60) return sec + "s";
  var min = Math.floor(sec / 60);
  if (min < 60) return min + "m";
  var hr = Math.floor(min / 60);
  if (hr < 24) return hr + "h " + (min % 60) + "m";
  var days = Math.floor(hr / 24);
  return days + "d " + (hr % 24) + "h";
}

function buildAgentRow(a) {
  var inactive = isAgentInactive(a);
  var color = getResolvedAgentColor(a.name);
  var liveness = a.liveness || (inactive ? "offline" : "online");
  var statusColor = livenessColor(liveness);
  var statusLabel = liveness;
  var agentIcon = getSenderIcon(a.name, true, 24);
  var dotHtml =
    '<span class="status-dot-inline" style="background:' + statusColor + '"></span>' +
    '<span class="status-label" style="color:' + statusColor + '">' +
    statusLabel + "</span>";
  var uniqueChannels = [...new Set(a.channels || [])];
  var channelsHtml = uniqueChannels.map(function(c) {
    return '<span class="ch-badge">' + escapeHtml(c) + "</span>";
  }).join("");
  var pinIcon = a.pinned ? "\uD83D\uDCCC" : "\uD83D\uDCCD";
  var pinTitle = a.pinned ? "Unpin" : "Pin";
  var pinBtnHtml =
    '<button class="pin-btn' + (a.pinned ? " pinned" : "") +
    '" data-pin-name="' + escapeHtml(a.name) +
    '" title="' + pinTitle +
    '" onclick="event.stopPropagation();togglePinAgent(\'' +
    escapeHtml(a.name).replace(/'/g, "\\'") + "', " + !a.pinned + ')">' +
    pinIcon + "</button>";
  var rowClass =
    "agent-row" +
    (inactive ? " agent-inactive" : "") +
    (a.pinned && inactive ? " pinned-offline" : "");
  return (
    '<tr class="' + rowClass + '" data-agent-name="' + escapeHtml(a.name) + '">' +
    "<td>" + pinBtnHtml + "</td>" +
    '<td><button class="kill-btn" data-kill-name="' + escapeHtml(a.name) +
    '" title="Kill agent" onclick="event.stopPropagation();killAgent(\'' +
    escapeHtml(a.name).replace(/'/g, "\\'") + "', this)\">\u2715</button>" +
    '<button class="restart-btn" data-restart-name="' + escapeHtml(a.name) +
    '" title="Restart agent" onclick="event.stopPropagation();restartAgent(\'' +
    escapeHtml(a.name).replace(/'/g, "\\'") + "', this)\">\u21BB</button></td>" +
    '<td class="agent-icon-cell avatar-clickable" data-avatar-agent="' + escapeHtml(a.name) +
    '" title="Click to change avatar" onclick="event.stopPropagation();openAvatarPicker(\'' +
    escapeHtml(a.name).replace(/'/g, "\\'") + "')\">" + agentIcon + "</td>" +
    "<td>" + dotHtml + "</td>" +
    '<td class="agent-id-cell">' + escapeHtml(cleanAgentName(a.agent_id || a.name)) + "</td>" +
    "<td>" + escapeHtml(a.role || "agent") + "</td>" +
    '<td class="monospace-cell">' + escapeHtml(a.machine || "unknown") + "</td>" +
    '<td class="muted-cell">' + escapeHtml(a.model || "-") + "</td>" +
    '<td class="muted-cell">' + escapeHtml(a.multiplexer || "-") + "</td>" +
    '<td class="ctx-cell">' + renderContextBadge(a.context_pct) + "</td>" +
    '<td class="skills-cell">' + renderSkillsBadge(a.skills_loaded) + "</td>" +
    '<td class="pid-cell muted-cell">' + (a.pid ? String(a.pid) : "-") + "</td>" +
    '<td class="small-cell">' + channelsHtml + "</td>" +
    '<td class="muted-cell">' + escapeHtml(a.project || "-") + "</td>" +
    '<td class="monospace-cell small-cell" title="' + escapeHtml(a.workdir || "") + '">' +
    escapeHtml(a.workdir ? a.workdir.replace(/^\/home\/[^/]+/, "~") : "-") + "</td>" +
    '<td class="task-cell">' + escapeHtml(a.current_task || "-") + "</td>" +
    '<td class="small-cell">' +
    (a.subagents && a.subagents.length > 0
      ? a.subagents.map(function(s) {
          var sClass = s.status === "done" ? "subagent-done" : "subagent-running";
          return '<span class="subagent-badge ' + sClass + '" title="' +
            escapeHtml(s.task || "") + '">' + escapeHtml(s.name || "subagent") + '</span>';
        }).join(" ")
      : (a.subagent_count && a.subagent_count > 0
          ? '<span class="subagent-badge subagent-running" title="' +
            a.subagent_count + ' subagent(s)">\uD83D\uDD27 ' + a.subagent_count + '</span>'
          : '<span class="muted-cell">-</span>')) +
    "</td>" +
    "<td>" +
    (a.claude_md
      ? '<button class="claude-md-btn" onclick="event.stopPropagation();toggleClaudeMd(this)" title="View CLAUDE.md">CLAUDE.md</button>'
      : '<span class="muted-cell">-</span>') +
    "</td>" +
    '<td class="muted-cell" title="Registered: ' + escapeHtml(a.registered_at || "") + '">' +
    formatUptime(a.registered_at) + "</td>" +
    '<td class="muted-cell" title="' + escapeHtml(a.last_action || "") + '">' +
    (a.idle_seconds != null
      ? '<span class="idle-badge idle-' + liveness + '">' + formatUptime(a.last_action) + ' ago</span>'
      : timeAgo(a.last_action)) +
    "</td>" +
    '<td class="muted-cell" title="' + escapeHtml(a.last_heartbeat || "") + '">' +
    (typeof relativeAge === "function" ? relativeAge(a.last_heartbeat) : timeAgo(a.last_heartbeat)) +
    "</td>" +
    "</tr>" +
    (function() {
      var raw = a.pane_tail_block || a.pane_tail || "";
      if (!raw) return "";
      var lines = String(raw).split(/\r?\n/);
      var tail = lines.slice(-10).join("\n");
      return (
        '<tr class="agent-pane-row"><td colspan="22">' +
        '<pre class="agent-pane-preview" title="Last 10 lines of ' + escapeHtml(a.name) + ' tmux pane">' +
        escapeHtml(tail) + "</pre></td></tr>"
      );
    })() +
    (a.claude_md
      ? '<tr class="claude-md-detail" style="display:none"><td colspan="22"><pre class="claude-md-content">' +
        escapeHtml(a.claude_md) + "</pre></td></tr>"
      : "")
  );
}

/* Toggle CLAUDE.md detail row visibility */
function toggleClaudeMd(btn) {
  var row = btn.closest("tr");
  var detailRow = row.nextElementSibling;
  if (detailRow && detailRow.classList.contains("claude-md-detail")) {
    var visible = detailRow.style.display !== "none";
    detailRow.style.display = visible ? "none" : "table-row";
    btn.textContent = visible ? "CLAUDE.md" : "Hide";
  }
}

function renderContextBadge(pct) {
  if (pct == null) return '<span class="muted-cell">-</span>';
  var n = Number(pct);
  if (isNaN(n)) return '<span class="muted-cell">-</span>';
  var color;
  if (n < 50) color = "#4ecdc4";
  else if (n < 80) color = "#ffd93d";
  else color = "#ef4444";
  return (
    '<span class="ctx-badge" title="Context window used" ' +
    'style="background:' + color + ';color:#111;padding:1px 6px;' +
    'border-radius:10px;font-size:11px;font-weight:600">ctx ' +
    n.toFixed(1) + "%</span>"
  );
}

function renderSkillsBadge(skills) {
  if (!skills || !skills.length) return '<span class="muted-cell">-</span>';
  var tip = skills.map(function(s){ return String(s); }).join("\n");
  return (
    '<span class="skills-badge" title="' + escapeHtml(tip) + '" ' +
    'style="background:#2a3340;color:#9ecbff;padding:1px 6px;' +
    'border-radius:10px;font-size:11px">skills:' + skills.length + "</span>"
  );
}

/* Auto-refresh: 3s when a per-agent tab is active, 1s for overview */
function startAgentsTabRefresh() {
  stopAgentsTabRefresh();
  _agentsTabInterval = setInterval(function() {
    if (activeTab === "agents-tab") renderAgentsTab();
  }, 3000);
}
function stopAgentsTabRefresh() {
  if (_agentsTabInterval) {
    clearInterval(_agentsTabInterval);
    _agentsTabInterval = null;
  }
}

async function purgeStaleAgents() {
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
