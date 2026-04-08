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
  var color = percent > 80 ? "#ef4444" : percent > 60 ? "#f59e0b" : "#4ecdc4";
  return (
    '<div class="res-bar-row"><span class="res-bar-label">' +
    label +
    '</span><div class="res-bar-track"><div class="res-bar-fill"></div></div>' +
    '<span class="res-bar-val">' +
    Math.round(percent) +
    "%</span></div>"
  );
}

function renderResources() {
  var container = document.getElementById("resources");
  var keys = Object.keys(resourceData);
  if (keys.length === 0) {
    container.innerHTML = '<p class="empty-notice">No reports yet</p>';
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
}

function renderResourcesTab() {
  var grid = document.getElementById("resources-grid");
  var keys = Object.keys(resourceData);
  if (keys.length === 0) {
    grid.innerHTML = '<p class="empty-notice">No resource reports yet.</p>';
    return;
  }
  grid.innerHTML = keys.map(buildResourceCard).join("");
  grid.querySelectorAll(".res-card[data-host-name]").forEach(function (el) {
    el.addEventListener("click", function () {
      addTag("host", el.getAttribute("data-host-name"));
    });
  });
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
  var html =
    '<div class="res-card" data-host-name="' +
    escapeHtml(k) +
    '">' +
    '<div class="res-host"><span class="res-dot"></span>' +
    escapeHtml(k) +
    "</div>" +
    subtitleHtml +
    barHtml("CPU", cpu) +
    barHtml("Mem", mem) +
    barHtml("Disk", diskPct);
  if (d.gpu && d.gpu.length > 0) {
    d.gpu.forEach(function (g) {
      html += barHtml("GPU", g.utilization_percent || 0);
    });
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

async function fetchResources() {
  try {
    var res = await fetch(apiUrl("/api/resources"));
    if (!res.ok) return;
    var data = await res.json();
    Object.keys(data).forEach(function (agentName) {
      var entry = data[agentName];
      var r = entry.resources || {};
      resourceData[agentName] = {
        hostname: entry.machine || agentName,
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
