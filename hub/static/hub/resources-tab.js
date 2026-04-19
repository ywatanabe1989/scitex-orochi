/* Resource Monitor Panel + Resources Tab */
/* globals: escapeHtml, activeTab, addTag, apiUrl, renderConnectivityMap */

var resourceData = {};

/* todo#86: hover tooltip for machine nodes/sidebar rows. Shared singleton
 * popover positioned near cursor, populated from resourceData[host]. */
var _machineTooltipEl = null;
function _machineTooltip() {
  if (_machineTooltipEl) return _machineTooltipEl;
  var el = document.createElement("div");
  el.className = "machine-hover-tooltip";
  el.setAttribute("role", "tooltip");
  el.style.display = "none";
  document.body.appendChild(el);
  _machineTooltipEl = el;
  return el;
}

function _fmtMetricPct(p) {
  /* 0 treated as "unknown / stale" to match bar/donut rendering. */
  if (!p || p <= 0) return { text: "\u2014", cls: "mh-tip-unknown" };
  var rounded = Math.round(p);
  var cls =
    rounded > 80 ? "mh-tip-crit" : rounded > 60 ? "mh-tip-warn" : "mh-tip-ok";
  return { text: rounded + "%", cls: cls };
}

function _machineMetricsHtml(host) {
  var d = resourceData[host];
  if (!d) return "";
  var cpu = (d.cpu && d.cpu.percent) || 0;
  var ram = (d.memory && d.memory.percent) || 0;
  var gpu = 0;
  var vram = 0;
  if (d.gpu && d.gpu.length > 0) {
    var g0 = d.gpu[0];
    gpu = g0.utilization_percent || 0;
    if (g0.memory_percent) {
      vram = g0.memory_percent;
    } else if (g0.memory_total_mb) {
      vram = ((g0.memory_used_mb || 0) / g0.memory_total_mb) * 100;
    }
  }
  var disk = 0;
  if (d.disk) {
    var dk = Object.keys(d.disk)[0];
    if (dk) disk = d.disk[dk].percent || 0;
  }
  function row(label, value) {
    var m = _fmtMetricPct(value);
    return (
      '<div class="mh-tip-row"><span class="mh-tip-label">' +
      label +
      '</span><span class="mh-tip-val ' +
      m.cls +
      '">' +
      m.text +
      "</span></div>"
    );
  }
  return (
    '<div class="mh-tip-host">' +
    escapeHtml(host) +
    "</div>" +
    row("CPU", cpu) +
    row("RAM", ram) +
    row("GPU", gpu) +
    row("VRAM", vram) +
    row("Disk", disk)
  );
}

function _positionMachineTooltip(el, evt) {
  /* Prefer top-right of cursor; clamp inside viewport. */
  var pad = 12;
  var rect = el.getBoundingClientRect();
  var vw = window.innerWidth;
  var vh = window.innerHeight;
  var x = evt.clientX + pad;
  var y = evt.clientY + pad;
  if (x + rect.width + pad > vw) x = evt.clientX - rect.width - pad;
  if (y + rect.height + pad > vh) y = evt.clientY - rect.height - pad;
  if (x < pad) x = pad;
  if (y < pad) y = pad;
  el.style.left = x + "px";
  el.style.top = y + "px";
}

function showMachineTooltip(host, evt) {
  if (!host) return;
  var html = _machineMetricsHtml(host);
  if (!html) return;
  var el = _machineTooltip();
  el.innerHTML = html;
  el.style.display = "block";
  _positionMachineTooltip(el, evt);
}

function moveMachineTooltip(evt) {
  if (!_machineTooltipEl || _machineTooltipEl.style.display === "none") return;
  _positionMachineTooltip(_machineTooltipEl, evt);
}

function hideMachineTooltip() {
  if (_machineTooltipEl) _machineTooltipEl.style.display = "none";
}

/* Expose for connectivity-map.js (SVG machine nodes). */
window.showMachineTooltip = showMachineTooltip;
window.moveMachineTooltip = moveMachineTooltip;
window.hideMachineTooltip = hideMachineTooltip;

/* Machines tab [Viz | Cards] view mode — persisted in localStorage.
 * "viz"   = connectivity-map (SSH mesh); resource cards hidden
 * "cards" = resource cards grid (default); connectivity-map hidden
 * ywatanabe 2026-04-19: matches the Agents tab [Viz|List] switch. */
var _machinesView = "cards";
try {
  var _persistedMV = localStorage.getItem("orochi.machinesView");
  if (_persistedMV === "viz" || _persistedMV === "cards")
    _machinesView = _persistedMV;
} catch (_e) {}

function _applyMachinesViewVisibility() {
  var connEl = document.getElementById("connectivity-map");
  var gridEl = document.getElementById("resources-grid");
  if (connEl) connEl.style.display = _machinesView === "viz" ? "" : "none";
  if (gridEl) gridEl.style.display = _machinesView === "cards" ? "" : "none";
}

var _machinesControlsWired = false;
function _wireMachinesControls() {
  if (_machinesControlsWired) return;
  var viewSwitch = document.querySelector(".machines-view-switch");
  if (!viewSwitch) return;
  function _setBtnActive() {
    viewSwitch
      .querySelectorAll(".machines-view-switch-btn")
      .forEach(function (b) {
        b.classList.toggle(
          "active",
          b.getAttribute("data-view") === _machinesView,
        );
      });
  }
  _setBtnActive();
  viewSwitch.addEventListener("click", function (ev) {
    var btn = ev.target.closest(".machines-view-switch-btn[data-view]");
    if (!btn) return;
    var next = btn.getAttribute("data-view");
    if (next === _machinesView) return;
    _machinesView = next;
    try {
      localStorage.setItem("orochi.machinesView", _machinesView);
    } catch (_e) {}
    _setBtnActive();
    _applyMachinesViewVisibility();
    /* If switching to Viz and the connectivity cache is empty, trigger
     * a fetch so the map paints instead of showing "No connectivity
     * data." forever. */
    if (_machinesView === "viz") {
      if (typeof renderConnectivityMap === "function") renderConnectivityMap();
      if (typeof fetchConnectivity === "function") fetchConnectivity();
    }
  });
  _machinesControlsWired = true;
}

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
  /* 0% is almost always stale/unknown data — show dash instead (#9692) */
  if (p === 0) {
    return (
      '<div class="res-bar-row"><span class="res-bar-label">' +
      label +
      '</span><div class="res-bar-track"><div class="res-bar-fill" style="width:0%;background:#444"></div></div>' +
      '<span class="res-bar-val res-bar-unknown">\u2014</span></div>'
    );
  }
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
  var radius = 26;
  var circumference = 2 * Math.PI * radius;
  /* 0% is almost always stale/unknown data — show dash instead (#9692) */
  if (p === 0) {
    return (
      '<div class="res-donut">' +
      '<svg class="res-donut-svg" viewBox="0 0 64 64" width="64" height="64">' +
      '<circle class="res-donut-bg" cx="32" cy="32" r="' +
      radius +
      '" ' +
      'fill="none" stroke="#1f1f1f" stroke-width="8"/>' +
      '<text x="32" y="36" text-anchor="middle" class="res-donut-text res-donut-unknown">\u2014</text>' +
      "</svg>" +
      '<div class="res-donut-label">' +
      label +
      "</div>" +
      "</div>"
    );
  }
  var color = p > 80 ? "#ef4444" : p > 60 ? "#f59e0b" : "#4ecdc4";
  var offset = circumference * (1 - p / 100);
  return (
    '<div class="res-donut">' +
    '<svg class="res-donut-svg" viewBox="0 0 64 64" width="64" height="64">' +
    '<circle class="res-donut-bg" cx="32" cy="32" r="' +
    radius +
    '" ' +
    'fill="none" stroke="#1f1f1f" stroke-width="8"/>' +
    '<circle class="res-donut-fg" cx="32" cy="32" r="' +
    radius +
    '" ' +
    'fill="none" stroke="' +
    color +
    '" stroke-width="8" ' +
    'stroke-dasharray="' +
    circumference.toFixed(2) +
    '" ' +
    'stroke-dashoffset="' +
    offset.toFixed(2) +
    '" ' +
    'stroke-linecap="round" transform="rotate(-90 32 32)"/>' +
    '<text x="32" y="36" text-anchor="middle" class="res-donut-text">' +
    p +
    "%</text>" +
    "</svg>" +
    '<div class="res-donut-label">' +
    label +
    "</div>" +
    "</div>"
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
      try {
        msgInput.setSelectionRange(savedStart, savedEnd);
      } catch (_) {}
    }
    return;
  }
  /* Sidebar machines = one-line rows (ywatanabe 2026-04-19: "name only
   * and connectivity and pin; X%, Y/Z GB, A/B TB"). Connectivity dot
   * on the left; host name color-coded by its own hash; compact chips
   * for CPU% / Mem Y/Z GB / Disk%. Total disk GB/TB isn't pushed by
   * heartbeat yet, so disk stays percent-only for now. */
  container.innerHTML = keys
    .map(function (k) {
      var d = resourceData[k];
      var health = (d.health && d.health.status) || "healthy";
      var healthy = health === "healthy";
      var cpu = (d.cpu && d.cpu.percent) || 0;
      var memPct = (d.memory && d.memory.percent) || 0;
      var memTotalMb =
        (d.memory && d.memory.total_mb) ||
        (d._metrics && d._metrics.mem_total_mb) ||
        0;
      var memStr = "—";
      if (memTotalMb > 0) {
        var memTotalGb = memTotalMb / 1024;
        var memUsedGb = (memTotalMb * memPct) / 100 / 1024;
        memStr = memUsedGb.toFixed(1) + "/" + memTotalGb.toFixed(0) + "GB";
      } else if (memPct > 0) {
        memStr = memPct.toFixed(0) + "%";
      }
      var diskPct = 0;
      if (d.disk) {
        var dk = Object.keys(d.disk)[0];
        if (dk) diskPct = d.disk[dk].percent || 0;
      }
      var color =
        typeof getAgentColor === "function" ? getAgentColor(k) : "#e6e6e6";
      var gpuStr = "";
      if (d.gpu && d.gpu.length > 0) {
        gpuStr =
          ' <span class="res-chip" title="GPU utilization">' +
          Math.round(d.gpu[0].utilization_percent || 0) +
          "% gpu</span>";
      }
      var slurmStr = "";
      if (d.slurm && d.slurm.total_jobs > 0) {
        slurmStr =
          ' <span class="res-chip" title="SLURM jobs">' +
          d.slurm.total_jobs +
          " jobs</span>";
      }
      return (
        '<div class="res-card res-card-compact" data-machine="' +
        escapeHtml(k) +
        '" title="' +
        escapeHtml(k) +
        (d._status ? " · " + d._status : "") +
        '">' +
        '<span class="res-conn res-conn-' +
        (healthy ? "ok" : "stale") +
        '"></span>' +
        '<span class="res-host-name" style="color:' +
        color +
        '">' +
        escapeHtml(k) +
        "</span>" +
        '<span class="res-metrics">' +
        '<span class="res-chip" title="CPU %">' +
        Math.round(cpu) +
        "%</span>" +
        '<span class="res-chip" title="Mem used/total">' +
        escapeHtml(memStr) +
        "</span>" +
        '<span class="res-chip" title="Disk %">' +
        Math.round(diskPct) +
        "%</span>" +
        gpuStr +
        slurmStr +
        "</span>" +
        "</div>"
      );
    })
    .join("");
  /* todo#86: hover tooltip on sidebar rows with CPU/RAM/GPU/VRAM/Disk. */
  container.querySelectorAll(".res-card[data-machine]").forEach(function (el) {
    var host = el.getAttribute("data-machine");
    el.addEventListener("mouseenter", function (ev) {
      showMachineTooltip(host, ev);
    });
    el.addEventListener("mousemove", moveMachineTooltip);
    el.addEventListener("mouseleave", hideMachineTooltip);
  });
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
}

function renderResourcesTab() {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  _wireMachinesControls();
  _applyMachinesViewVisibility();
  var grid = document.getElementById("resources-grid");
  var keys = Object.keys(resourceData);
  if (keys.length === 0) {
    grid.innerHTML = '<p class="empty-notice">No resource reports yet.</p>';
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try {
        msgInput.setSelectionRange(savedStart, savedEnd);
      } catch (_) {}
    }
    return;
  }
  grid.innerHTML = keys.map(buildResourceCard).join("");
  grid.querySelectorAll(".res-card[data-host-name]").forEach(function (el) {
    el.addEventListener("click", function () {
      addTag("host", el.getAttribute("data-host-name"));
    });
    /* todo#51: bidirectional hover-sync with SSH-mesh + activity cards. */
    el.addEventListener("mouseenter", function () {
      if (typeof syncHostHover === "function")
        syncHostHover(el.getAttribute("data-host-name"), true);
    });
    el.addEventListener("mouseleave", function () {
      if (typeof syncHostHover === "function")
        syncHostHover(el.getAttribute("data-host-name"), false);
    });
  });
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
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
      gpuRow += donutHtml(
        "GPU" + (d.gpu.length > 1 ? i + 1 : ""),
        g.utilization_percent || 0,
      );
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
      if (
        existing &&
        !existing._api &&
        (r.mem_used_percent || 0) === 0 &&
        (existing.memory || {}).percent > 0
      )
        return;
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
