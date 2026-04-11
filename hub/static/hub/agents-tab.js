/* Agents Tab -- registry table with location/machine visualization */
/* globals: escapeHtml, getAgentColor, isAgentInactive, timeAgo,
   addTag, activeTab, apiUrl */
var _agentsTabInterval = null;

async function renderAgentsTab() {
  var grid = document.getElementById("agents-grid");
  try {
    var res = await fetch(apiUrl("/api/agents/registry"));
    var agents = await res.json();
    if (agents.length === 0) {
      grid.innerHTML = '<p class="empty-notice">No agents connected</p>';
      return;
    }
    /* Group agents by machine for summary */
    var machineMap = {};
    agents.forEach(function (a) {
      var m = a.machine || "unknown";
      if (!machineMap[m]) machineMap[m] = [];
      machineMap[m].push(a);
    });
    /* Sort: online first, then offline */
    agents.sort(function (a, b) {
      var aOff = isAgentInactive(a) ? 1 : 0;
      var bOff = isAgentInactive(b) ? 1 : 0;
      return aOff - bOff || a.name.localeCompare(b.name);
    });
    var onlineCount = agents.filter(function (a) {
      return !isAgentInactive(a);
    }).length;
    var offlineCount = agents.length - onlineCount;
    var purgeBtn =
      offlineCount > 0
        ? ' <button class="purge-btn" onclick="purgeStaleAgents()" title="Remove all offline agents from registry">Purge offline (' +
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
          var badgeClass =
            online === total
              ? "machine-ok"
              : online > 0
                ? "machine-warn"
                : "machine-off";
          return (
            '<span class="machine-badge ' +
            badgeClass +
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
    /* Build table */
    var tableHtml =
      '<table class="agents-registry-table">' +
      "<thead><tr>" +
      "<th>Pin</th>" +
      "<th>Icon</th>" +
      "<th>Status</th>" +
      "<th>Agent ID</th>" +
      "<th>Role</th>" +
      "<th>Host / Machine</th>" +
      "<th>Model</th>" +
      "<th>Channels</th>" +
      "<th>Project</th>" +
      "<th>Workdir</th>" +
      "<th>Task</th>" +
      "<th>Config</th>" +
      "<th>Registered</th>" +
      "<th>Last Seen</th>" +
      "</tr></thead><tbody>" +
      agents.map(buildAgentRow).join("") +
      "</tbody></table>";
    grid.innerHTML = summaryHtml + tableHtml;
    /* Click row to add agent filter tag */
    grid.querySelectorAll(".agent-row[data-agent-name]").forEach(function (el) {
      el.addEventListener("click", function () {
        addTag("agent", el.getAttribute("data-agent-name"));
      });
    });
  } catch (e) {
    console.error("Agents tab error:", e);
  }
}

function buildAgentRow(a) {
  var inactive = isAgentInactive(a);
  var color = getResolvedAgentColor(a.name);
  var statusColor = inactive ? "#ef4444" : "#4ecdc4";
  var statusLabel = inactive ? "offline" : "online";
  var agentIcon = cachedAgentIcons[a.name]
    ? getSenderIcon(a.name, true)
    : getLetterIcon(a.name, 20);
  var dotHtml =
    '<span class="status-dot-inline"></span>' +
    '<span class="status-label">' +
    statusLabel +
    "</span>";
  var uniqueChannels = [...new Set(a.channels || [])];
  var channelsHtml = uniqueChannels
    .map(function (c) {
      return '<span class="ch-badge">' + escapeHtml(c) + "</span>";
    })
    .join("");
  var pinIcon = a.pinned ? "\uD83D\uDCCC" : "\uD83D\uDCCD";
  var pinTitle = a.pinned ? "Unpin" : "Pin";
  var pinBtnHtml =
    '<button class="pin-btn' + (a.pinned ? " pinned" : "") +
    '" data-pin-name="' + escapeHtml(a.name) +
    '" title="' + pinTitle + '" onclick="event.stopPropagation();togglePinAgent(\'' +
    escapeHtml(a.name).replace(/'/g, "\\'") + "', " + (!a.pinned) + ')">' +
    pinIcon + '</button>';
  var rowClass = "agent-row" + (inactive ? " agent-inactive" : "") + (a.pinned && inactive ? " pinned-offline" : "");
  return (
    '<tr class="' +
    rowClass +
    '" data-agent-name="' +
    escapeHtml(a.name) +
    '">' +
    "<td>" + pinBtnHtml + "</td>" +
    '<td class="agent-icon-cell">' + agentIcon + "</td>" +
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
    '<td class="small-cell">' +
    channelsHtml +
    "</td>" +
    '<td class="muted-cell">' +
    escapeHtml(a.project || "-") +
    "</td>" +
    '<td class="monospace-cell small-cell" title="' + escapeHtml(a.workdir || "") + '">' +
    escapeHtml(a.workdir ? a.workdir.replace(/^\/home\/[^/]+/, "~") : "-") +
    "</td>" +
    '<td class="task-cell">' +
    escapeHtml(a.current_task || "-") +
    "</td>" +
    "<td>" +
    (a.claude_md
      ? '<button class="claude-md-btn" onclick="event.stopPropagation();toggleClaudeMd(this)" title="View CLAUDE.md">CLAUDE.md</button>'
      : '<span class="muted-cell">-</span>') +
    "</td>" +
    '<td class="muted-cell" title="' +
    escapeHtml(a.registered_at || "") +
    '">' +
    timeAgo(a.registered_at) +
    "</td>" +
    '<td class="muted-cell" title="' +
    escapeHtml(a.last_heartbeat || "") +
    '">' +
    timeAgo(a.last_heartbeat) +
    "</td>" +
    "</tr>" +
    (a.claude_md
      ? '<tr class="claude-md-detail" style="display:none"><td colspan="14"><pre class="claude-md-content">' +
        escapeHtml(a.claude_md) +
        "</pre></td></tr>"
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

/* Auto-refresh agents tab every 10s when visible */
function startAgentsTabRefresh() {
  stopAgentsTabRefresh();
  _agentsTabInterval = setInterval(function () {
    if (activeTab === "agents-tab") renderAgentsTab();
  }, 10000);
}
function stopAgentsTabRefresh() {
  if (_agentsTabInterval) {
    clearInterval(_agentsTabInterval);
    _agentsTabInterval = null;
  }
}

/* Purge all offline/stale agents via API */
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

/* Start auto-refresh on load */
startAgentsTabRefresh();
