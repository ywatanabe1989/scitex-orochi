/* Resource Monitor Panel + Resources Tab — part 1: state, icons, tooltip,
 * machines-view switch, donut/bar helpers, updateResourcePanel.
 * Split from resources-tab.js (697 lines) — see resources-tab/tab.js for
 * the renderers and fetchResources. */
/* globals: escapeHtml, renderConnectivityMap */

var resourceData = {};

/* Per-user machine icon overrides stored in localStorage. Keyed by
 * machine short-label. Custom emoji only (image upload deferred —
 * parallel to the channel canvas image fix). Right-click on a
 * sidebar machine row opens the shared emoji picker to set; empty
 * string clears back to the default 🖥. TODO.md Entity Consistency:
 * "Icons (svg/png) must be configurable ... machine: which icon
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
