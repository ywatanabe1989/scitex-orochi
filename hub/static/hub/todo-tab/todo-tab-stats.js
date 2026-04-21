/* TODO stats dashboard (#171) — totals / burn-down / label breakdown
 * / by-repo / starvation. Backend: GET /api/todo/stats/ cached 60s.   */
/* globals: escapeHtml */

var _todoStatsRefreshTimer = null;
var _TODO_STATS_REFRESH_MS = 60 * 1000; /* matches backend CACHE_TTL_S */

function _shortRepo(repo) {
  if (!repo) return "";
  var slash = repo.lastIndexOf("/");
  return slash >= 0 ? repo.substring(slash + 1) : repo;
}

function _renderTodoStatsTotals(totals) {
  var openN = (totals && totals.open) || 0;
  var closedN = (totals && totals.closed) || 0;
  var total = openN + closedN;
  return (
    '<div class="todo-stats-cards">' +
    '<div class="todo-stats-card"><div class="todo-stats-val">' +
    openN +
    "</div>" +
    '<div class="todo-stats-lbl">Open</div></div>' +
    '<div class="todo-stats-card"><div class="todo-stats-val">' +
    closedN +
    "</div>" +
    '<div class="todo-stats-lbl">Closed</div></div>' +
    '<div class="todo-stats-card"><div class="todo-stats-val">' +
    total +
    "</div>" +
    '<div class="todo-stats-lbl">Total</div></div>' +
    "</div>"
  );
}

/* Inline SVG burn-down: two polylines (opened, closed) over the window. */
function _renderTodoStatsBurndown(daily) {
  if (!daily || daily.length === 0) {
    return '<p class="empty-notice">No velocity data</p>';
  }
  var W = 720,
    H = 180;
  var padL = 32,
    padR = 12,
    padT = 12,
    padB = 24;
  var innerW = W - padL - padR;
  var innerH = H - padT - padB;
  var n = daily.length;
  var maxY = 1;
  for (var i = 0; i < n; i++) {
    if (daily[i].opened > maxY) maxY = daily[i].opened;
    if (daily[i].closed > maxY) maxY = daily[i].closed;
  }
  /* Round maxY up for nicer axis */
  var step = n > 1 ? innerW / (n - 1) : innerW;
  function pt(i, v) {
    var x = padL + i * step;
    var y = padT + innerH - (v / maxY) * innerH;
    return x.toFixed(1) + "," + y.toFixed(1);
  }
  var openedPath = daily
    .map(function (d, i) {
      return pt(i, d.opened);
    })
    .join(" ");
  var closedPath = daily
    .map(function (d, i) {
      return pt(i, d.closed);
    })
    .join(" ");

  /* Y-axis ticks at 0, maxY/2, maxY */
  function yLabel(v) {
    var y = padT + innerH - (v / maxY) * innerH;
    return (
      '<text class="todo-chart-axis" x="' +
      (padL - 4) +
      '" y="' +
      (y + 3) +
      '" text-anchor="end">' +
      v +
      "</text>" +
      '<line class="todo-chart-grid" x1="' +
      padL +
      '" x2="' +
      (W - padR) +
      '" y1="' +
      y +
      '" y2="' +
      y +
      '"/>'
    );
  }
  var yLabels = yLabel(0) + yLabel(Math.round(maxY / 2)) + yLabel(maxY);

  /* X-axis: show first, middle, last date */
  function xLabel(i) {
    if (i < 0 || i >= n) return "";
    var x = padL + i * step;
    var label = (daily[i].date || "").substring(5); /* MM-DD */
    return (
      '<text class="todo-chart-axis" x="' +
      x +
      '" y="' +
      (H - 6) +
      '" text-anchor="middle">' +
      label +
      "</text>"
    );
  }
  var xLabels = xLabel(0) + xLabel(Math.floor(n / 2)) + xLabel(n - 1);

  return (
    '<div class="todo-stats-section">' +
    '<div class="todo-stats-h">Daily velocity (14d)</div>' +
    '<div class="todo-chart-legend">' +
    '<span class="todo-chart-swatch todo-chart-opened"></span>Opened ' +
    '<span class="todo-chart-swatch todo-chart-closed"></span>Closed' +
    "</div>" +
    '<svg class="todo-chart" viewBox="0 0 ' +
    W +
    " " +
    H +
    '" preserveAspectRatio="none" role="img" aria-label="Daily open/close velocity">' +
    yLabels +
    xLabels +
    '<polyline class="todo-chart-line todo-chart-opened-line" points="' +
    openedPath +
    '"/>' +
    '<polyline class="todo-chart-line todo-chart-closed-line" points="' +
    closedPath +
    '"/>' +
    "</svg>" +
    "</div>"
  );
}

function _renderTodoStatsLabels(labels) {
  if (!labels || labels.length === 0) {
    return (
      '<div class="todo-stats-section"><div class="todo-stats-h">Labels</div>' +
      '<p class="empty-notice">No labels</p></div>'
    );
  }
  var maxCount = labels[0].open_count || 1;
  var rows = labels
    .map(function (l) {
      var pct = Math.max(2, Math.round((l.open_count / maxCount) * 100));
      return (
        '<li class="todo-label-row">' +
        '<span class="todo-label-name">' +
        escapeHtml(l.label) +
        "</span>" +
        '<span class="todo-label-bar"><span class="todo-label-fill" style="width:' +
        pct +
        '%"></span></span>' +
        '<span class="todo-label-count">' +
        l.open_count +
        "</span>" +
        "</li>"
      );
    })
    .join("");
  return (
    '<div class="todo-stats-section">' +
    '<div class="todo-stats-h">Labels (open, top ' +
    labels.length +
    ")</div>" +
    '<ul class="todo-label-list">' +
    rows +
    "</ul>" +
    "</div>"
  );
}

/* BY REPO horizontal bar chart (msg#16206, msg#16207). Renders below
 * DAILY VELOCITY + LABELS. Each repo is one row with a stacked
 * open/closed bar and the pair of counts at the right. Sorted by
 * total (open+closed) descending so the busiest repo is on top. The
 * colour palette reuses the burndown legend swatches (opened=red,
 * closed=green) so the three viz sections read consistently. */
function _renderTodoStatsByRepo(rows) {
  if (!rows || rows.length === 0) {
    return "";
  }
  /* Work on a sorted copy so we don't mutate the cached payload the
   * next render pass (or another section) may read. */
  var sorted = rows.slice().sort(function (a, b) {
    var ta = (a.open || 0) + (a.closed || 0);
    var tb = (b.open || 0) + (b.closed || 0);
    return tb - ta;
  });
  var maxTotal = 1;
  sorted.forEach(function (r) {
    var t = (r.open || 0) + (r.closed || 0);
    if (t > maxTotal) maxTotal = t;
  });
  var body = sorted
    .map(function (r) {
      var openN = r.open || 0;
      var closedN = r.closed || 0;
      /* Each segment's width is proportional to the count relative to
       * the busiest repo's total — so repos with fewer issues render
       * shorter bars, just like the LABELS chart. Clamp to >=0 so an
       * empty row collapses rather than producing a negative width. */
      var openPct = Math.max(0, (openN / maxTotal) * 100);
      var closedPct = Math.max(0, (closedN / maxTotal) * 100);
      return (
        '<li class="todo-repo-row">' +
        '<span class="todo-repo-name">' +
        escapeHtml(_shortRepo(r.repo)) +
        "</span>" +
        '<span class="todo-repo-bar">' +
        '<span class="todo-repo-fill todo-repo-fill-open" style="width:' +
        openPct.toFixed(2) +
        '%" title="Open: ' +
        openN +
        '"></span>' +
        '<span class="todo-repo-fill todo-repo-fill-closed" style="width:' +
        closedPct.toFixed(2) +
        '%" title="Closed: ' +
        closedN +
        '"></span>' +
        "</span>" +
        '<span class="todo-repo-counts">' +
        '<span class="todo-repo-count todo-repo-count-open">' +
        openN +
        "</span>" +
        '<span class="todo-repo-count-sep">/</span>' +
        '<span class="todo-repo-count todo-repo-count-closed">' +
        closedN +
        "</span>" +
        "</span>" +
        "</li>"
      );
    })
    .join("");
  return (
    '<div class="todo-stats-section">' +
    '<div class="todo-stats-h">By repo (open / closed, ' +
    sorted.length +
    ")</div>" +
    '<div class="todo-chart-legend">' +
    '<span class="todo-chart-swatch todo-chart-opened"></span>Open ' +
    '<span class="todo-chart-swatch todo-chart-closed"></span>Closed' +
    "</div>" +
    '<ul class="todo-repo-list">' +
    body +
    "</ul>" +
    "</div>"
  );
}

function _renderTodoStatsStarvation(rows, threshold) {
  if (!rows || rows.length === 0) {
    return (
      '<div class="todo-stats-section"><div class="todo-stats-h">Starvation</div>' +
      '<p class="empty-notice">Nothing stale — good job</p></div>'
    );
  }
  var body = rows
    .map(function (r) {
      var labels = (r.labels || [])
        .map(function (n) {
          return '<span class="todo-label">' + escapeHtml(n) + "</span>";
        })
        .join("");
      return (
        "<tr>" +
        "<td>" +
        escapeHtml(_shortRepo(r.repo)) +
        "</td>" +
        '<td class="todo-repo-num">#' +
        escapeHtml(String(r.number)) +
        "</td>" +
        '<td><a href="' +
        escapeHtml(r.url || "#") +
        '" target="_blank" rel="noopener">' +
        escapeHtml(r.title || "") +
        "</a></td>" +
        '<td class="todo-repo-num">' +
        (r.age_days || 0) +
        "d</td>" +
        '<td><div class="todo-labels">' +
        labels +
        "</div></td>" +
        "</tr>"
      );
    })
    .join("");
  return (
    '<div class="todo-stats-section">' +
    '<div class="todo-stats-h">Starvation (open &gt; ' +
    (threshold || 7) +
    "d, top " +
    rows.length +
    ")</div>" +
    '<table class="todo-starve-table">' +
    "<thead><tr><th>Repo</th><th>#</th><th>Title</th><th>Age</th><th>Labels</th></tr></thead>" +
    "<tbody>" +
    body +
    "</tbody>" +
    "</table>" +
    "</div>"
  );
}

function _renderTodoStats(data) {
  var container = document.getElementById("todo-stats");
  if (!container) return;
  if (!data) {
    container.innerHTML = '<p class="empty-notice">No TODO stats available</p>';
    return;
  }
  var html =
    _renderTodoStatsTotals(data.totals) +
    _renderTodoStatsBurndown(data.daily_velocity) +
    _renderTodoStatsLabels(data.label_breakdown) +
    _renderTodoStatsByRepo(data.by_repo) +
    _renderTodoStatsStarvation(data.starvation, data.starvation_threshold_days);
  container.innerHTML = html;
}

async function fetchTodoStats(force) {
  var container = document.getElementById("todo-stats");
  if (!container) return;
  if (!container.innerHTML) {
    container.innerHTML = '<p class="empty-notice">Loading TODO stats...</p>';
  }
  try {
    var url = "/api/todo/stats/" + (force ? "?refresh=1" : "");
    var res = await fetch(url, { credentials: "same-origin" });
    if (!res.ok) {
      container.innerHTML =
        '<p class="empty-notice">Failed to load TODO stats (HTTP ' +
        res.status +
        ")</p>";
      return;
    }
    var data = await res.json();
    _renderTodoStats(data);
  } catch (e) {
    console.error("TODO stats fetch error:", e);
    container.innerHTML =
      '<p class="empty-notice">Failed to load TODO stats</p>';
  }
}

function startTodoStatsAutoRefresh() {
  if (_todoStatsRefreshTimer) return;
  _todoStatsRefreshTimer = setInterval(fetchTodoStats, _TODO_STATS_REFRESH_MS);
}

function stopTodoStatsAutoRefresh() {
  if (_todoStatsRefreshTimer) {
    clearInterval(_todoStatsRefreshTimer);
    _todoStatsRefreshTimer = null;
  }
}

/* Wire up: kick off stats fetch + auto-refresh when the TODO tab is clicked.
 * Mirrors the activity-tab pattern (DOMContentLoaded → bind click on
 * data-tab button → refresh + startAutoRefresh). The existing fetchTodoList
 * flow for the issue list is untouched. */
document.addEventListener("DOMContentLoaded", function () {
  var btn = document.querySelector('[data-tab="todo"]');
  if (btn) {
    btn.addEventListener("click", function () {
      fetchTodoStats();
      startTodoStatsAutoRefresh();
    });
  }
  /* If the TODO tab is the default-restored tab on reload, fetch stats once
   * on first load too (tabs.js calls _activateTab before this handler binds). */
  try {
    var last = localStorage.getItem("orochi_active_tab");
    if (last === "todo") {
      fetchTodoStats();
      startTodoStatsAutoRefresh();
    }
  } catch (_) {}
});
