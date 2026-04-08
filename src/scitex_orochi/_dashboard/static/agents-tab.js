/* Agents Tab -- registry table with location/machine visualization */
/* globals: escapeHtml, getAgentColor, isAgentInactive, timeAgo, addTag, activeTab */
var _agentsTabInterval = null;

async function renderAgentsTab() {
  var grid = document.getElementById("agents-grid");
  try {
    var res = await fetch("/api/agents/registry");
    var agents = await res.json();
    if (agents.length === 0) {
      grid.innerHTML =
        '<p style="color:#555;font-size:13px;">No agents connected</p>';
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
      '<span style="color:#aaa;font-size:12px;margin-right:12px;">' +
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
          var color =
            online === total ? "#4ecdc4" : online > 0 ? "#ffd93d" : "#ef4444";
          return (
            '<span class="machine-badge" style="background:' +
            color +
            "22;color:" +
            color +
            ";border:1px solid " +
            color +
            '44;padding:2px 8px;border-radius:4px;font-size:11px;margin-right:6px">' +
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
      el.style.cursor = "pointer";
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
    '<span style="display:inline-block;width:8px;height:8px;' +
    "border-radius:50%;background:" +
    statusColor +
    ';margin-right:6px;vertical-align:middle"></span>' +
    '<span style="color:' +
    statusColor +
    ';font-size:12px">' +
    statusLabel +
    "</span>";
  var channelsHtml = (a.channels || [])
    .map(function (c) {
      return (
        '<span style="background:#333;padding:1px 5px;' +
        'border-radius:3px;margin-right:3px">' +
        escapeHtml(c) +
        "</span>"
      );
    })
    .join("");
  return (
    "<tr" +
    (inactive ? ' style="opacity:0.5"' : "") +
    ' class="agent-row" data-agent-name="' +
    escapeHtml(a.name) +
    '">' +
    "<td>" +
    dotHtml +
    "</td>" +
    '<td style="color:' +
    color +
    ';font-weight:600">' +
    escapeHtml(a.agent_id || a.name) +
    "</td>" +
    "<td>" +
    escapeHtml(a.role || "agent") +
    "</td>" +
    '<td style="font-family:monospace;font-size:12px">' +
    escapeHtml(a.machine || "unknown") +
    "</td>" +
    '<td style="color:#888;font-size:12px">' +
    escapeHtml(a.model || "-") +
    "</td>" +
    '<td style="font-size:12px">' +
    channelsHtml +
    "</td>" +
    '<td style="color:#ffd93d;font-size:12px;max-width:200px;' +
    'overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' +
    escapeHtml(a.current_task || "-") +
    "</td>" +
    '<td style="color:#888;font-size:12px" title="' +
    escapeHtml(a.registered_at || "") +
    '">' +
    timeAgo(a.registered_at) +
    "</td>" +
    '<td style="color:#888;font-size:12px" title="' +
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
