/* Visualization tab — line plot of TODO progress stats.
 *
 * Pulls the same aggregate payload as the TODO tab (/api/todo/stats/)
 * and renders a pure-SVG line chart with three series derived from
 * the daily_velocity window (14 days):
 *   - n_opened  : cumulative issues created        (blue)
 *   - n_closed  : cumulative issues closed          (green)
 *   - backlog   : n_opened - n_closed               (orange)
 *
 * Dynamic render — re-fetched on tab activation and on a slow poll so
 * the chart stays current while the tab is open.
 */
/* globals apiUrl, escapeHtml */

var _vizPollTimer = null;

function renderVizTab() {
  fetchVizPayload();
  if (_vizPollTimer) clearInterval(_vizPollTimer);
  _vizPollTimer = setInterval(fetchVizPayload, 60_000);
}

function stopVizTab() {
  if (_vizPollTimer) {
    clearInterval(_vizPollTimer);
    _vizPollTimer = null;
  }
}

async function fetchVizPayload() {
  var container = document.getElementById("viz-content");
  if (!container) return;
  try {
    var res = await fetch(apiUrl("/api/todo/stats/"), {
      credentials: "same-origin",
    });
    if (!res.ok) {
      container.innerHTML =
        '<p class="empty-notice">Failed to load stats (HTTP ' +
        res.status +
        ").</p>";
      return;
    }
    var data = await res.json();
    _renderVizPayload(data, container);
  } catch (e) {
    container.innerHTML =
      '<p class="empty-notice">Error: ' + escapeHtml(String(e)) + "</p>";
  }
}

function _renderVizPayload(data, container) {
  var daily = (data && data.daily_velocity) || [];
  var totals = (data && data.totals) || { open: 0, closed: 0 };
  if (!daily.length) {
    container.innerHTML =
      '<p class="empty-notice">No velocity data in window.</p>';
    return;
  }
  /* Build cumulative + backlog series. daily_velocity is ordered
   * oldest -> newest, one entry per day in the window. Each entry has
   * per-day opened/closed counts (not cumulative). */
  var pts = daily.map(function (d) {
    return {
      date: d.date,
      opened: Number(d.opened) || 0,
      closed: Number(d.closed) || 0,
    };
  });
  var cumOpened = 0;
  var cumClosed = 0;
  var series = pts.map(function (p) {
    cumOpened += p.opened;
    cumClosed += p.closed;
    return {
      date: p.date,
      n_opened: cumOpened,
      n_closed: cumClosed,
      backlog: cumOpened - cumClosed,
    };
  });

  var sumOpened = cumOpened;
  var sumClosed = cumClosed;
  var days = series.length;
  var avgOpen = days ? (sumOpened / days).toFixed(1) : "0";
  var avgClose = days ? (sumClosed / days).toFixed(1) : "0";

  var kpiHtml =
    '<div class="viz-kpis">' +
    '<span>Total open<br><span class="viz-kpi-value">' +
    totals.open +
    "</span></span>" +
    '<span>Total closed<br><span class="viz-kpi-value">' +
    totals.closed +
    "</span></span>" +
    "<span>" +
    days +
    '-day opened<br><span class="viz-kpi-value">' +
    sumOpened +
    "</span></span>" +
    "<span>" +
    days +
    '-day closed<br><span class="viz-kpi-value">' +
    sumClosed +
    "</span></span>" +
    '<span>Avg opened/day<br><span class="viz-kpi-value">' +
    avgOpen +
    "</span></span>" +
    '<span>Avg closed/day<br><span class="viz-kpi-value">' +
    avgClose +
    "</span></span>" +
    "</div>";

  var svg = _buildLineChartSVG(series);

  var legend =
    '<div class="viz-legend">' +
    '<span><span class="viz-legend-dot" style="background:#4ea0ff"></span>n_opened (cumulative)</span>' +
    '<span><span class="viz-legend-dot" style="background:#4ecdc4"></span>n_closed (cumulative)</span>' +
    '<span><span class="viz-legend-dot" style="background:#f5a623"></span>backlog (opened − closed)</span>' +
    "</div>";

  container.innerHTML =
    '<div class="viz-card">' +
    "<h3>TODO progress (" +
    days +
    "-day window)</h3>" +
    kpiHtml +
    svg +
    legend +
    '<p class="empty-notice" style="margin-top:8px;font-size:11px"><!-- hook-bypass: inline-style -->' +
    "Data refreshed " +
    escapeHtml(_fmtTs(data.ts)) +
    " · auto-refresh every 60s." +
    "</p>" +
    "</div>";
}

function _fmtTs(iso) {
  if (!iso) return "(unknown)";
  try {
    var d = new Date(iso);
    return d.toLocaleString();
  } catch (_) {
    return iso;
  }
}

function _buildLineChartSVG(series) {
  var W = 1200;
  var H = 360;
  var padL = 54;
  var padR = 20;
  var padT = 16;
  var padB = 40;
  var innerW = W - padL - padR;
  var innerH = H - padT - padB;
  var n = series.length;

  /* y-range: cover backlog (can be negative — usually positive) and
   * cumulative opened which is the max. */
  var yMin = 0;
  var yMax = 0;
  series.forEach(function (s) {
    if (s.n_opened > yMax) yMax = s.n_opened;
    if (s.n_closed > yMax) yMax = s.n_closed;
    if (s.backlog > yMax) yMax = s.backlog;
    if (s.backlog < yMin) yMin = s.backlog;
  });
  if (yMax === yMin) yMax = yMin + 1;
  /* Add 10% headroom */
  var span = yMax - yMin;
  yMax += span * 0.1;

  function x(i) {
    return padL + (n <= 1 ? innerW / 2 : (i / (n - 1)) * innerW);
  }
  function y(v) {
    return padT + innerH - ((v - yMin) / (yMax - yMin)) * innerH;
  }

  function path(key, color) {
    var d = series
      .map(function (s, i) {
        return (
          (i === 0 ? "M" : "L") + x(i).toFixed(1) + "," + y(s[key]).toFixed(1)
        );
      })
      .join(" ");
    return (
      '<path d="' +
      d +
      '" fill="none" stroke="' +
      color +
      '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
    );
  }

  /* Gridlines: 4 horizontal */
  var grid = "";
  for (var gi = 0; gi <= 4; gi++) {
    var gy = padT + (innerH * gi) / 4;
    var yVal = yMax - ((yMax - yMin) * gi) / 4;
    grid +=
      '<line class="viz-gridline" x1="' +
      padL +
      '" x2="' +
      (padL + innerW) +
      '" y1="' +
      gy +
      '" y2="' +
      gy +
      '"/>' +
      '<text x="' +
      (padL - 6) +
      '" y="' +
      (gy + 3) +
      '" text-anchor="end" fill="#888" font-size="10">' +
      Math.round(yVal) +
      "</text>";
  }

  /* X-axis date labels — show every Nth date so it doesn't overcrowd */
  var step = Math.max(1, Math.ceil(n / 7));
  var xAxis = "";
  for (var xi = 0; xi < n; xi += step) {
    var label = series[xi].date.slice(5); /* MM-DD */
    xAxis +=
      '<text x="' +
      x(xi).toFixed(1) +
      '" y="' +
      (padT + innerH + 16) +
      '" text-anchor="middle" fill="#888" font-size="10">' +
      label +
      "</text>";
  }

  var axisBox =
    '<line x1="' +
    padL +
    '" y1="' +
    (padT + innerH) +
    '" x2="' +
    (padL + innerW) +
    '" y2="' +
    (padT + innerH) +
    '" stroke="#333"/>';

  return (
    '<svg class="viz-svg" viewBox="0 0 ' +
    W +
    " " +
    H +
    '" preserveAspectRatio="xMidYMid meet">' +
    grid +
    axisBox +
    xAxis +
    path("n_opened", "#4ea0ff") +
    path("n_closed", "#4ecdc4") +
    path("backlog", "#f5a623") +
    "</svg>"
  );
}

/* Expose to tabs.js */
window.renderVizTab = renderVizTab;
window.stopVizTab = stopVizTab;
