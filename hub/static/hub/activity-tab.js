/* Activity tab — real-time agent status board */
/* globals: apiUrl, escapeHtml, getAgentColor, cleanAgentName, fetchAgents */

var activityRefreshTimer = null;

function _formatIdle(seconds) {
  if (seconds == null) return "";
  if (seconds < 60) return seconds + "s";
  if (seconds < 3600) return Math.floor(seconds / 60) + "m";
  return Math.floor(seconds / 3600) + "h";
}

function _livenessLabel(liveness) {
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

function _livenessOrder(liveness) {
  /* Sort: stale first (needs attention), then online, idle, offline */
  switch (liveness) {
    case "stale": return 0;
    case "online": return 1;
    case "idle": return 2;
    case "offline": return 3;
    default: return 4;
  }
}

function _renderTaskField(task) {
  if (!task) return '<span class="activity-task-empty">no task reported</span>';
  /* Linkify #NNN issue refs */
  var safe = escapeHtml(task);
  return safe.replace(
    /#(\d+)\b/g,
    '<a class="issue-link" href="https://github.com/ywatanabe1989/scitex-orochi/issues/$1" target="_blank">#$1</a>',
  );
}

function renderActivityTab() {
  var grid = document.getElementById("activity-grid");
  var summary = document.getElementById("activity-summary");
  if (!grid) return;

  /* Reuse the global agents cache populated by fetchAgents() */
  var src = window.__lastAgents || [];
  if (!src.length) {
    grid.innerHTML = '<p class="empty-notice">No agents connected.</p>';
    if (summary) summary.textContent = "";
    return;
  }

  var agents = src.slice().sort(function (a, b) {
    var oa = _livenessOrder(a.liveness || a.status);
    var ob = _livenessOrder(b.liveness || b.status);
    if (oa !== ob) return oa - ob;
    return (a.name || "").localeCompare(b.name || "");
  });

  var counts = { online: 0, idle: 0, stale: 0, offline: 0 };
  agents.forEach(function (a) {
    var l = a.liveness || a.status || "online";
    if (counts[l] != null) counts[l]++;
  });

  if (summary) {
    summary.innerHTML =
      '<span class="activity-pill activity-pill-online">' + counts.online + ' active</span>' +
      '<span class="activity-pill activity-pill-idle">' + counts.idle + ' idle</span>' +
      '<span class="activity-pill activity-pill-stale">' + counts.stale + ' stale</span>' +
      '<span class="activity-pill activity-pill-offline">' + counts.offline + ' offline</span>';
  }

  grid.innerHTML = agents.map(function (a) {
    var color = getAgentColor(a.name);
    var liveness = a.liveness || a.status || "online";
    var idleStr = _formatIdle(a.idle_seconds);
    var task = a.current_task || "";
    var preview = a.last_message_preview || "";
    var machine = escapeHtml(a.machine || "—");
    var role = escapeHtml(a.role || "agent");
    var name = escapeHtml(
      typeof hostedAgentName === "function" ? hostedAgentName(a) : cleanAgentName(a.name),
    );
    var previewHtml = preview
      ? '<div class="activity-preview">' +
        '<span class="activity-preview-label">last:</span> ' +
        escapeHtml(preview) +
        '</div>'
      : "";
    var subagents = Array.isArray(a.subagents) ? a.subagents : [];
    var subagentsHtml = "";
    if (subagents.length > 0) {
      subagentsHtml =
        '<ul class="activity-subagents">' +
        subagents
          .map(function (s) {
            var sname = escapeHtml(s.name || "subagent");
            var stask = _renderTaskField(s.task || "");
            var sstatus = escapeHtml(s.status || "running");
            return (
              '<li class="activity-subagent activity-subagent-' + sstatus + '">' +
              '<span class="activity-subagent-branch">└─</span>' +
              '<span class="activity-subagent-name">' + sname + '</span>' +
              '<span class="activity-subagent-task">' + stask + '</span>' +
              '</li>'
            );
          })
          .join("") +
        "</ul>";
    }
    return (
      '<div class="activity-card activity-' + liveness + '">' +
      '<div class="activity-card-header">' +
      '<span class="activity-status-dot activity-dot-' + liveness + '"></span>' +
      '<span class="activity-name" style="color:' + color + '">' + name + '</span>' +
      '<span class="activity-liveness">' + _livenessLabel(liveness) + (idleStr ? ' · ' + idleStr : '') + '</span>' +
      '</div>' +
      '<div class="activity-meta">' + machine + ' · ' + role + '</div>' +
      '<div class="activity-task">' + _renderTaskField(task) + '</div>' +
      subagentsHtml +
      previewHtml +
      '</div>'
    );
  }).join("");
}

async function refreshActivityFromApi() {
  try {
    var res = await fetch(apiUrl("/api/agents"), { credentials: "same-origin" });
    if (!res.ok) return;
    window.__lastAgents = await res.json();
    renderActivityTab();
  } catch (e) {
    /* ignore */
  }
}

function startActivityAutoRefresh() {
  if (activityRefreshTimer) return;
  activityRefreshTimer = setInterval(refreshActivityFromApi, 10000);
}

function stopActivityAutoRefresh() {
  if (activityRefreshTimer) {
    clearInterval(activityRefreshTimer);
    activityRefreshTimer = null;
  }
}

document.addEventListener("DOMContentLoaded", function () {
  var btn = document.querySelector('[data-tab="activity"]');
  if (btn) {
    btn.addEventListener("click", function () {
      refreshActivityFromApi();
      startActivityAutoRefresh();
    });
  }
});
