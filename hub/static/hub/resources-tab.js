/* Resource Monitor Panel + Resources Tab */
/* globals: escapeHtml, activeTab, addTag, apiUrl */

var resourceData = {};

function updateResourcePanel(data) {
  var key = data.hostname || data.agent || "unknown";
  resourceData[key] = data;
  renderResources();
}

function healthColor(status) {
  if (status === "critical") return "#ef4444";
  if (status === "warning") return "#f59e0b";
  return "#4ecdc4";
}

function barHtml(label, percent) {
  var p = Math.min(100, Math.max(0, Math.round(percent)));
  var color = p > 80 ? "#ef4444" : p > 60 ? "#f59e0b" : "#4ecdc4";
  return (
    '<div class="res-bar-row"><span class="res-bar-label">' +
    label +
    '</span><div class="res-bar-track"><div class="res-bar-fill" style="width:' +
    p +
    "%;background:" +
    color +
    '"></div></div>' +
    '<span class="res-bar-val">' +
    p +
    "%</span></div>"
  );
}

/* Donut (pie-chart) for machine resources — inline SVG, no deps */
function donutHtml(label, percent) {
  var p = Math.min(100, Math.max(0, Math.round(percent)));
  var color = p > 80 ? "#ef4444" : p > 60 ? "#f59e0b" : "#4ecdc4";
  var radius = 26;
  var circumference = 2 * Math.PI * radius;
  var offset = circumference * (1 - p / 100);
  return (
    '<div class="res-donut">' +
    '<svg class="res-donut-svg" viewBox="0 0 64 64" width="64" height="64">' +
    '<circle class="res-donut-bg" cx="32" cy="32" r="' + radius + '" ' +
    'fill="none" stroke="#1f1f1f" stroke-width="8"/>' +
    '<circle class="res-donut-fg" cx="32" cy="32" r="' + radius + '" ' +
    'fill="none" stroke="' + color + '" stroke-width="8" ' +
    'stroke-dasharray="' + circumference.toFixed(2) + '" ' +
    'stroke-dashoffset="' + offset.toFixed(2) + '" ' +
    'stroke-linecap="round" transform="rotate(-90 32 32)"/>' +
    '<text x="32" y="36" text-anchor="middle" class="res-donut-text">' + p + '%</text>' +
    '</svg>' +
    '<div class="res-donut-label">' + label + '</div>' +
    '</div>'
  );
}

function renderResources() {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var container = document.getElementById("resources");
  var keys = Object.keys(resourceData);
  var cEl = document.getElementById("sidebar-count-machines");
  if (cEl) cEl.textContent = keys.length ? "(" + keys.length + ")" : "";
  if (keys.length === 0) {
    container.innerHTML = '<p class="empty-notice">No reports yet</p>';
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
    }
    return;
  }
  container.innerHTML = keys
    .map(function (k) {
      var d = resourceData[k];
      var health = (d.health && d.health.status) || "healthy";
      var hColor = healthColor(health);
      var cpu = (d.cpu && d.cpu.percent) || 0;
      var mem = (d.memory && d.memory.percent) || 0;
      var diskPct = 0;
      if (d.disk) {
        var dk = Object.keys(d.disk)[0];
        if (dk) diskPct = d.disk[dk].percent || 0;
      }
      var html =
        '<div class="res-card">' +
        '<div class="res-host"><span class="res-dot"></span>' +
        escapeHtml(k) +
        "</div>" +
        barHtml("CPU", cpu) +
        barHtml("Mem", mem) +
        barHtml("Disk", diskPct);
      if (d.gpu && d.gpu.length > 0) {
        d.gpu.forEach(function (g) {
          html += barHtml("GPU", g.utilization_percent || 0);
        });
      }
      if (d._loadAvg) {
        html +=
          '<div class="res-meta">Load: ' +
          d._loadAvg
            .map(function (v) {
              return v.toFixed(1);
            })
            .join(" / ") +
          "</div>";
      }
      if (d._status) {
        html += '<div class="res-meta">' + escapeHtml(d._status) + "</div>";
      }
      if (d.slurm && d.slurm.total_jobs > 0) {
        html +=
          '<div class="res-meta">SLURM: ' + d.slurm.total_jobs + " jobs</div>";
      }
      html += "</div>";
      return html;
    })
    .join("");
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
  }
}

function renderResourcesTab() {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var grid = document.getElementById("resources-grid");
  var keys = Object.keys(resourceData);
  if (keys.length === 0) {
    grid.innerHTML = '<p class="empty-notice">No resource reports yet.</p>';
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
    }
    return;
  }
  grid.innerHTML = keys.map(buildResourceCard).join("");
  grid.querySelectorAll(".res-card[data-host-name]").forEach(function (el) {
    el.addEventListener("click", function () {
      addTag("host", el.getAttribute("data-host-name"));
    });
  });
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
  }
}

function buildResourceCard(k) {
  var d = resourceData[k];
  var health = (d.health && d.health.status) || "healthy";
  var cpu = (d.cpu && d.cpu.percent) || 0;
  var mem = (d.memory && d.memory.percent) || 0;
  var diskPct = 0;
  if (d.disk) {
    var dk = Object.keys(d.disk)[0];
    if (dk) diskPct = d.disk[dk].percent || 0;
  }
  var subtitleParts = [];
  if (d._machine) subtitleParts.push(escapeHtml(d._machine));
  if (d._status) {
    subtitleParts.push(escapeHtml(d._status));
  }
  var subtitleHtml =
    subtitleParts.length > 0
      ? '<div class="res-meta">' + subtitleParts.join(" &middot; ") + "</div>"
      : "";
  var loadHtml = "";
  if (d._loadAvg) {
    loadHtml =
      '<div class="res-meta">Load avg: ' +
      d._loadAvg
        .map(function (v) {
          return v.toFixed(2);
        })
        .join(" / ") +
      "</div>";
  }
  var memDetail = "";
  if (d._memTotalMb) {
    var usedMb = Math.round(d._memTotalMb - (d._memFreeMb || 0));
    memDetail =
      '<div class="res-meta">' + usedMb + " / " + d._memTotalMb + " MB</div>";
  }
  var cpuInfo = "";
  if (d._cpuCount) {
    cpuInfo =
      '<div class="res-meta">' +
      d._cpuCount +
      " cores" +
      (d._cpuModel ? " &middot; " + escapeHtml(d._cpuModel) : "") +
      "</div>";
  }
  var donutRow =
    '<div class="res-donut-row">' +
    donutHtml("CPU", cpu) +
    donutHtml("Mem", mem) +
    donutHtml("Disk", diskPct) +
    "</div>";
  var html =
    '<div class="res-card" data-host-name="' +
    escapeHtml(k) +
    '">' +
    '<div class="res-host"><span class="res-dot"></span>' +
    escapeHtml(k) +
    "</div>" +
    subtitleHtml +
    donutRow;
  if (d.gpu && d.gpu.length > 0) {
    var gpuRow = '<div class="res-donut-row">';
    d.gpu.forEach(function (g, i) {
      gpuRow += donutHtml("GPU" + (d.gpu.length > 1 ? (i + 1) : ""), g.utilization_percent || 0);
    });
    gpuRow += "</div>";
    html += gpuRow;
  }
  html += loadHtml + cpuInfo + memDetail;
  if (d.subagents !== undefined) {
    html += '<div class="res-meta">Subagents: ' + d.subagents + "</div>";
  }
  if (d.docker && d.docker.containers !== undefined) {
    html +=
      '<div class="res-meta">Containers: ' + d.docker.containers + "</div>";
  }
  if (d.uptime) {
    html += '<div class="res-meta">Uptime: ' + escapeHtml(d.uptime) + "</div>";
  }
  if (d._lastHeartbeat) {
    var hbDate = new Date(d._lastHeartbeat);
    var hbStr = isNaN(hbDate.getTime())
      ? d._lastHeartbeat
      : hbDate.toLocaleString();
    html += '<div class="res-meta">Heartbeat: ' + escapeHtml(hbStr) + "</div>";
  }
  html += "</div>";
  return html;
}

/* todo#337: friendly canonical names so DXP480TPLUS-994 shows as "nas" etc. */
var MACHINE_ALIASES = {
  "DXP480TPLUS-994": "nas",
  "Yusukes-MacBook-Air.local": "mba",
  "spartan-login1.hpc.unimelb.edu.au": "spartan",
  "spartan-login1": "spartan",
};
function _friendlyMachine(raw) {
  if (!raw) return raw;
  if (MACHINE_ALIASES[raw]) return MACHINE_ALIASES[raw] + " (" + raw + ")";
  return raw;
}

async function fetchResources() {
  try {
    var res = await fetch(apiUrl("/api/resources"));
    if (!res.ok) return;
    var data = await res.json();
    Object.keys(data).forEach(function (agentName) {
      var entry = data[agentName];
      var r = entry.resources || {};
      /* Don't overwrite richer WS data with empty REST metrics (#337) */
      var existing = resourceData[agentName];
      if (existing && !existing._api && (r.mem_used_percent || 0) === 0 && (existing.memory || {}).percent > 0) return;
      resourceData[agentName] = {
        hostname: _friendlyMachine(entry.machine || agentName),
        agent: agentName,
        cpu: {
          percent: Math.round(
            ((r.load_avg_1m || 0) / Math.max(r.cpu_count || 1, 1)) * 100,
          ),
        },
        memory: { percent: r.mem_used_percent || 0 },
        disk: { "/": { percent: r.disk_used_percent || 0 } },
        health: {
          status:
            r.mem_used_percent > 80 || r.disk_used_percent > 80
              ? "critical"
              : r.mem_used_percent > 60 || r.disk_used_percent > 60
                ? "warning"
                : "healthy",
        },
        _api: true,
        _status: entry.status || "unknown",
        _machine: entry.machine || "",
        _lastHeartbeat: entry.last_heartbeat || "",
        _cpuModel: r.cpu_model || "",
        _cpuCount: r.cpu_count || 0,
        _loadAvg: [r.load_avg_1m || 0, r.load_avg_5m || 0, r.load_avg_15m || 0],
        _memFreeMb: r.mem_free_mb || 0,
        _memTotalMb: r.mem_total_mb || 0,
      };
    });
    renderResources();
    if (activeTab === "resources") renderResourcesTab();
  } catch (e) {
    console.warn("fetchResources failed:", e);
  }
}
