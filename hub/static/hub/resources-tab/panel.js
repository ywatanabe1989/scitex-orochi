/* Resource Monitor Panel + Resources Tab — part 1: state, icons, tooltip,
 * machines-view switch, donut/bar helpers, updateResourcePanel.
 * Split from resources-tab.js (697 lines) — see resources-tab/tab.js for
 * the renderers and fetchResources. */
/* globals: escapeHtml, renderConnectivityMap */

var resourceData = {};

/* Per-user orochi_machine icon overrides stored in localStorage. Keyed by
 * orochi_machine short-label. Custom emoji only (image upload deferred —
 * parallel to the channel canvas image fix). Right-click on a
 * sidebar orochi_machine row opens the shared emoji picker to set; empty
 * string clears back to the default 🖥. TODO.md Entity Consistency:
 * "Icons (svg/png) must be configurable ... orochi_machine: which icon
 * would be good?" — default 🖥, user can pick anything from the
 * shared emoji picker. */
var _MACHINE_ICON_KEY = "orochi.machineIcons";
var _machineIcons = (function _loadMachineIcons() {
  try {
    var raw = localStorage.getItem(_MACHINE_ICON_KEY);
    if (!raw) return {};
    var parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (_e) {
    return {};
  }
})();
function _persistMachineIcons() {
  try {
    localStorage.setItem(_MACHINE_ICON_KEY, JSON.stringify(_machineIcons));
  } catch (_e) {
    /* ignore quota / private-mode errors */
  }
}
function setMachineIcon(name, emoji) {
  if (emoji) _machineIcons[name] = emoji;
  else delete _machineIcons[name];
  _persistMachineIcons();
  if (typeof renderResources === "function") renderResources();
}
window.setMachineIcon = setMachineIcon;

/* todo#86: hover tooltip for orochi_machine nodes/sidebar rows. Shared singleton
 * popover positioned near cursor, populated from resourceData[host]. */
var _machineTooltipEl = null;
function _machineTooltip() {
  if (_machineTooltipEl) return _machineTooltipEl;
  var el = document.createElement("div");
  el.className = "orochi_machine-hover-tooltip";
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

/* ywatanabe msg#16215 — classify an N/M metric by its fill ratio so
 * the tooltip keeps the green/yellow/red health semantics the donut
 * renderers already use. Unit formatting is the caller's job. */
function _classifyRatio(used, total) {
  if (!total || total <= 0) return "mh-tip-unknown";
  var pct = (used / total) * 100;
  return pct > 80 ? "mh-tip-crit" : pct > 60 ? "mh-tip-warn" : "mh-tip-ok";
}

function _machineMetricsHtml(host) {
  var d = resourceData[host];
  if (!d) return "";
  /* Spec (ywatanabe msg#16215): CPU=N cores, RAM=N/M GB,
   * Storage=N/M TB (1 decimal), GPU=N/M or n/a. */
  function row(label, text, cls) {
    return (
      '<div class="mh-tip-row"><span class="mh-tip-label">' +
      label +
      '</span><span class="mh-tip-val ' +
      (cls || "mh-tip-ok") +
      '">' +
      escapeHtml(text) +
      "</span></div>"
    );
  }
  var rows = [];
  var cpuCount = d._cpuCount || 0;
  if (cpuCount > 0) {
    rows.push(row("CPU", cpuCount + " cores", "mh-tip-ok"));
  } else {
    rows.push(row("CPU", "\u2014", "mh-tip-unknown"));
  }
  var memTotalMb = d._memTotalMb || 0;
  var memUsedMb = d._memUsedMb || 0;
  if (!memUsedMb && memTotalMb > 0) {
    memUsedMb = Math.max(0, memTotalMb - (d._memFreeMb || 0));
  }
  if (memTotalMb > 0) {
    rows.push(
      row(
        "RAM",
        Math.round(memUsedMb / 1024) + "/" + Math.round(memTotalMb / 1024) + " GB",
        _classifyRatio(memUsedMb, memTotalMb),
      ),
    );
  } else {
    rows.push(row("RAM", "\u2014", "mh-tip-unknown"));
  }
  var diskTotalMb = d._diskTotalMb || 0;
  var diskUsedMb = d._diskUsedMb || 0;
  if (diskTotalMb > 0) {
    var diskUsedTb = diskUsedMb / 1024 / 1024;
    var diskTotalTb = diskTotalMb / 1024 / 1024;
    rows.push(
      row(
        "Storage",
        diskUsedTb.toFixed(1) + "/" + diskTotalTb.toFixed(1) + " TB",
        _classifyRatio(diskUsedMb, diskTotalMb),
      ),
    );
  } else {
    var diskPct = 0;
    if (d.disk) {
      var dk = Object.keys(d.disk)[0];
      if (dk) diskPct = d.disk[dk].percent || 0;
    }
    var dm = _fmtMetricPct(diskPct);
    rows.push(row("Storage", dm.text, dm.cls));
  }
  if (d.gpu && d.gpu.length > 0) {
    var totalGpus = d.gpu.length;
    var usedGpus = d.gpu.filter(function (g) {
      return (g.utilization_percent || 0) > 5;
    }).length;
    var meanUtil =
      d.gpu.reduce(function (acc, g) {
        return acc + (g.utilization_percent || 0);
      }, 0) / totalGpus;
    rows.push(
      row(
        "GPU",
        usedGpus + "/" + totalGpus + " \u00B7 " + Math.round(meanUtil) + "%",
        _classifyRatio(usedGpus, totalGpus),
      ),
    );
    d.gpu.forEach(function (g, i) {
      if (!g.memory_total_mb) return;
      var usedGb = (g.memory_used_mb || 0) / 1024;
      var totalGb = g.memory_total_mb / 1024;
      rows.push(
        row(
          "VRAM" + (totalGpus > 1 ? i + 1 : ""),
          usedGb.toFixed(1) + "/" + totalGb.toFixed(1) + " GB",
          _classifyRatio(g.memory_used_mb || 0, g.memory_total_mb),
        ),
      );
    });
  } else {
    rows.push(row("GPU", "n/a", "mh-tip-unknown"));
  }
  return (
    '<div class="mh-tip-host">' + escapeHtml(host) + "</div>" + rows.join("")
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

/* Expose for connectivity-map.js (SVG orochi_machine nodes). */
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
  /* Scope the query — another .machines-view-switch was added inside
   * #todo-view for the TODO Viz/List toggle (todo#102). Without the
   * #resources-view prefix the selector matched the TODO one first
   * and the Machines tab switcher silently no-op'd. */
  var viewSwitch = document.querySelector(
    "#resources-view .machines-view-switch",
  );
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

/* Donut (pie-chart) for orochi_machine resources — inline SVG, no deps */
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
