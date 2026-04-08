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
    var summaryHtml =
      '<div class="agents-summary">' +
      '<span class="agents-count">' +
      agents.length +
      " agent(s) across " +
      Object.keys(machineMap).length +
      " machine(s)" +
      "</span>" +
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
      "<th>Status</th>" +
      "<th>Agent ID</th>" +
      "<th>Role</th>" +
      "<th>Host / Machine</th>" +
      "<th>Model</th>" +
      "<th>Channels</th>" +
      "<th>Task</th>" +
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
  var color = getAgentColor(a.name);
  var statusColor = inactive ? "#ef4444" : "#4ecdc4";
  var statusLabel = inactive ? "offline" : "online";
  var dotHtml =
    '<span class="status-dot-inline"></span>' +
    '<span class="status-label">' +
    statusLabel +
    "</span>";
  var channelsHtml = (a.channels || [])
    .map(function (c) {
      return '<span class="ch-badge">' + escapeHtml(c) + "</span>";
    })
    .join("");
  var rowClass = "agent-row" + (inactive ? " agent-inactive" : "");
  return (
    '<tr class="' +
    rowClass +
    '" data-agent-name="' +
    escapeHtml(a.name) +
    '">' +
    "<td>" +
    dotHtml +
    "</td>" +
    '<td class="agent-id-cell">' +
    escapeHtml(a.agent_id || a.name) +
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
    '<td class="task-cell">' +
    escapeHtml(a.current_task || "-") +
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
    "</tr>"
  );
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

/* Start auto-refresh on load */
startAgentsTabRefresh();
