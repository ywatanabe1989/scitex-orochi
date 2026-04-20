// @ts-nocheck
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
/* Cache the most recent stats payload so tab re-activation paints
 * instantly from memory while a background refetch runs. Without this
 * every tab switch waits on /api/todo/stats/ (which hits GitHub and is
 * perceptibly slow). */
var _vizCachedData = null;
var _vizCachedAt = 0;
var _VIZ_FRESH_MS = 60_000;
/* Signature of the last rendered payload. Background polls that return
 * the same data skip the DOM write entirely — avoids flashing the SVG
 * every 60s when nothing changed. */
var _vizRenderedSig = "";

function _vizSig(data) {
  try {
    var daily = (data && data.daily_velocity) || [];
    var totals = (data && data.totals) || {};
    return (
      String(totals.open || 0) +
      ":" +
      String(totals.closed || 0) +
      ":" +
      daily.length +
      ":" +
      (daily.length
        ? daily[daily.length - 1].date +
          "/" +
          daily[daily.length - 1].opened +
          "/" +
          daily[daily.length - 1].closed
        : "")
    );
  } catch (_) {
    return String(Date.now());
  }
}

function renderVizTab() {
  var container = document.getElementById("viz-content");
  if (!container) return;
  if (_vizCachedData) {
    /* Instant paint from cache — user sees the chart before the network
     * call returns. Force the signature write by resetting first so a
     * re-activation after the section was hidden still paints. */
    _vizRenderedSig = "";
    _renderVizPayload(_vizCachedData, container);
  } else if (!container.innerHTML) {
    /* No cache yet — paint a skeleton so the tab shell renders
     * immediately. The real chart replaces this as soon as the async
     * /api/todo/stats/ round-trip returns (todo#82). */
    container.innerHTML = _buildVizSkeleton();
  }
  /* Refetch if the cache is older than the poll interval. */
  if (Date.now() - _vizCachedAt > _VIZ_FRESH_MS) {
    fetchVizPayload();
  }
  if (_vizPollTimer) clearInterval(_vizPollTimer);
  _vizPollTimer = setInterval(fetchVizPayload, _VIZ_FRESH_MS);
}

function _buildVizSkeleton() {
  /* Lightweight placeholder — matches the real card geometry so the
   * layout doesn't jump when the SVG arrives. Pure CSS shimmer. */
  return (
    '<div class="viz-card viz-skeleton" aria-busy="true">' +
    "<h3>TODO progress</h3>" +
    '<div class="viz-skel-chart"></div>' +
    '<div class="viz-skel-legend">' +
    '<span class="viz-skel-pill"></span>' +
    '<span class="viz-skel-pill"></span>' +
    '<span class="viz-skel-pill"></span>' +
    "</div>" +
    '<div class="viz-skel-kpis">' +
    '<span class="viz-skel-kpi"></span>' +
    '<span class="viz-skel-kpi"></span>' +
    '<span class="viz-skel-kpi"></span>' +
    '<span class="viz-skel-kpi"></span>' +
    "</div>" +
    '<p class="empty-notice viz-skel-note">Loading visualization&hellip;</p>' +
    "</div>"
  );
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
      /* Don't clobber a cached chart on a transient 5xx — show the
       * error only when we have nothing on screen. */
      if (!_vizCachedData) {
        container.innerHTML =
          '<p class="empty-notice">Failed to load stats (HTTP ' +
          res.status +
          ").</p>";
      }
      return;
    }
    var data = await res.json();
    _vizCachedData = data;
    _vizCachedAt = Date.now();
    _renderVizPayload(data, container);
  } catch (e) {
    if (!_vizCachedData) {
      container.innerHTML =
        '<p class="empty-notice">Error: ' + escapeHtml(String(e)) + "</p>";
    }
  }
}

function _renderVizPayload(data, container) {
  /* Skip redundant re-renders — if the payload signature matches the
   * last render, the DOM is already correct. Saves the SVG rebuild on
   * every 60s poll when nothing changed. */
  var sig = _vizSig(data);
  if (sig && sig === _vizRenderedSig) return;
  _vizRenderedSig = sig;
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

  /* Chart first — ywatanabe 2026-04-19: "this is the most important
   * graph" / "the most bottom figure should be in the top". KPIs and
   * legend are secondary context; the time-series line chart gets
   * priority visual real estate at the top. */
  container.innerHTML =
    '<div class="viz-card">' +
    "<h3>TODO progress (" +
    days +
    "-day window)</h3>" +
    svg +
    legend +
    kpiHtml +
    '<p class="empty-notice" style="margin-top:8px;font-size:11px"><!-- hook-bypass: inline-style -->' +
    "Data refreshed " +
    escapeHtml(_fmtTs(data.ts)) +
    " · auto-refresh every 60s." +
    "</p>" +
    "</div>";
}

/* Background prefetch — ywatanabe 2026-04-19: "Vis in TODO quite slow;
 * why? is it not possible to get info in background?". Kick off the
 * /api/todo/stats/ fetch at page load so the cache is already warm by
 * the time the user clicks TODO > Viz. The chart then paints instantly
 * from cache instead of waiting for the round-trip. */
if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", function () {
    /* Delay 1s so we don't compete with the initial agents/stats/chat
     * fetches for the first paint — Viz is background, not critical. */
    setTimeout(function () {
      if (typeof fetchVizPayload === "function") fetchVizPayload();
    }, 1000);
  });
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
