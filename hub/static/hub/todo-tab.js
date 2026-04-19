/* TODO List -- GitHub Issues (grouped + expandable) */
/* globals: escapeHtml, addTag */

var PRIORITY_GROUPS = [
  { key: "high-priority", label: "High Priority", color: "#ef4444" },
  { key: "medium-priority", label: "Medium Priority", color: "#ffd93d" },
  { key: "low-priority", label: "Low Priority", color: "#4ecdc4" },
  { key: "future", label: "Future", color: "#888" },
  { key: "_uncategorized", label: "Uncategorized", color: "#555" },
];

function classifyIssue(issue) {
  var names = (issue.labels || []).map(function (l) {
    return l.name;
  });
  for (var i = 0; i < PRIORITY_GROUPS.length - 1; i++) {
    if (names.indexOf(PRIORITY_GROUPS[i].key) !== -1) {
      return PRIORITY_GROUPS[i].key;
    }
  }
  return "_uncategorized";
}

function sortByUpdated(a, b) {
  var da = a.updated_at || "";
  var db = b.updated_at || "";
  return da > db ? -1 : da < db ? 1 : 0;
}

function formatDate(iso) {
  if (!iso) return "";
  var d = new Date(iso);
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function normalizeBody(text) {
  if (!text) return "(no description)";
  return text.replace(/\r\n/g, "\n");
}

function buildLabelsHtml(labels) {
  if (!labels || labels.length === 0) return "";
  var spans = labels
    .map(function (label) {
      var bg = label.color ? "#" + label.color : "#333";
      var fg = isLightColor(label.color || "333333") ? "#000" : "#fff";
      return (
        '<span class="todo-label" data-label-name="' +
        escapeHtml(label.name) +
        '" style="background:' +
        bg +
        ";color:" +
        fg +
        '">' +
        escapeHtml(label.name) +
        "</span>"
      );
    })
    .join("");
  return '<div class="todo-labels">' + spans + "</div>";
}

/* Map of number -> issue, populated on each render. Used by lazy
 * detail rendering so the initial card list can skip the expensive
 * escapeHtml(body) pass for issues the user never expands. */
var _todoIssuesByNumber = {};

function buildDetailInnerHtml(issue) {
  var body = normalizeBody(issue.body || "");
  var assignee =
    issue.assignee && issue.assignee.login
      ? issue.assignee.login
      : "unassigned";
  var commentsCount = issue.comments || 0;
  var commentsHtml = "<span>Comments: " + commentsCount + "</span>";
  return (
    '<div class="todo-detail-body">' +
    escapeHtml(body) +
    "</div>" +
    '<div class="todo-detail-meta">' +
    "<span>Assignee: " +
    escapeHtml(assignee) +
    "</span>" +
    commentsHtml +
    "<span>Created: " +
    formatDate(issue.created_at) +
    "</span>" +
    "<span>Updated: " +
    formatDate(issue.updated_at) +
    "</span>" +
    '<a href="' +
    escapeHtml(issue.html_url) +
    '" target="_blank" rel="noopener" class="todo-detail-link" title="Open on GitHub">' +
    "&#x1F517;" +
    "</a>" +
    "</div>"
  );
}

function buildIssueCard(issue) {
  var labelsHtml = buildLabelsHtml(issue.labels);
  var assigneeHtml = "";
  if (issue.assignee && issue.assignee.login) {
    assigneeHtml =
      '<span class="todo-assignee">' +
      escapeHtml(issue.assignee.login) +
      "</span>";
  }
  var closedClass = issue.state === "closed" ? " closed" : "";
  var stateClass =
    issue.state === "open" ? "todo-state-open" : "todo-state-closed";
  var stateTitle = issue.state === "open" ? "Open" : "Closed";
  return (
    '<div class="todo-item' +
    closedClass +
    '" data-issue-number="' +
    issue.number +
    '">' +
    '<div class="todo-item-row">' +
    '<span class="todo-state-dot ' +
    stateClass +
    '" title="' +
    stateTitle +
    '"></span>' +
    '<span class="todo-number">#' +
    issue.number +
    "</span>" +
    '<span class="todo-title">' +
    escapeHtml(issue.title) +
    "</span>" +
    labelsHtml +
    assigneeHtml +
    '<span class="todo-chevron">&#9654;</span>' +
    "</div>" +
    '<div class="todo-detail"></div>' +
    "</div>"
  );
}

function _ensureDetailFilled(el) {
  var detail = el.querySelector(".todo-detail");
  if (!detail || detail.dataset.filled === "1") return;
  var num = el.getAttribute("data-issue-number");
  var issue = _todoIssuesByNumber[num];
  if (!issue) return;
  detail.innerHTML = buildDetailInnerHtml(issue);
  detail.dataset.filled = "1";
}

function buildGroupHtml(group, issues) {
  if (issues.length === 0) return "";
  return (
    '<div class="todo-group">' +
    '<div class="todo-group-header" style="border-left-color:' +
    group.color +
    '">' +
    '<span class="todo-group-label">' +
    escapeHtml(group.label) +
    "</span>" +
    '<span class="todo-group-count">' +
    issues.length +
    "</span>" +
    "</div>" +
    '<div class="todo-group-items">' +
    issues.map(buildIssueCard).join("") +
    "</div>" +
    "</div>"
  );
}

function attachTodoEvents(container) {
  container.querySelectorAll(".todo-item").forEach(function (el) {
    el.addEventListener("click", function (e) {
      if (e.target.closest(".todo-detail-link")) return;
      if (e.target.closest(".todo-label[data-label-name]")) return;
      e.preventDefault();
      _ensureDetailFilled(el);
      el.classList.toggle("expanded");
    });
  });
  container
    .querySelectorAll(".todo-label[data-label-name]")
    .forEach(function (el) {
      el.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        addTag("label", el.getAttribute("data-label-name"));
      });
      el.style.cursor = "pointer";
    });
}

/* Background-fill details after initial render so expanding is instant
 * and an inspector could search body text without waiting. Uses
 * requestIdleCallback where available to stay out of the way of user
 * interactions; fills in small chunks. */
function _backgroundFillDetails(container) {
  var els = Array.prototype.slice.call(
    container.querySelectorAll(".todo-item"),
  );
  var idx = 0;
  var CHUNK = 25;
  var schedule =
    window.requestIdleCallback ||
    function (cb) {
      return setTimeout(function () {
        cb({
          timeRemaining: function () {
            return 16;
          },
        });
      }, 1);
    };
  function tick(deadline) {
    var end = Math.min(idx + CHUNK, els.length);
    for (; idx < end; idx++) _ensureDetailFilled(els[idx]);
    if (idx < els.length) schedule(tick);
  }
  schedule(tick);
}

/* Active filter groups — Set so Ctrl/Cmd-click can multi-select */
var todoActiveGroups = new Set(["all"]);

function _syncTodoBtnState() {
  document.querySelectorAll(".todo-state-btn").forEach(function (b) {
    var g = b.getAttribute("data-group");
    b.classList.toggle("active", todoActiveGroups.has(g));
  });
}

/* Count issues per state-filter pill and inject the N into the button.
 * Labels are preserved as text and the count is rendered in a small
 * muted span so styling can target it independently. */
function _updateTodoBtnCounts(issues) {
  var counts = {
    all: 0,
    "high-priority": 0,
    "medium-priority": 0,
    "low-priority": 0,
    future: 0,
    blocker: 0,
    closed: 0,
  };
  (issues || []).forEach(function (issue) {
    counts.all += 1;
    if (issue.state === "closed") {
      counts.closed += 1;
      if (_hasBlockerLabel(issue)) counts.blocker += 1;
      return;
    }
    if (_hasBlockerLabel(issue)) counts.blocker += 1;
    var key = classifyIssue(issue);
    if (counts[key] != null) counts[key] += 1;
    else if (key === "_uncategorized") counts.future += 1;
  });
  var LABELS = {
    all: "All",
    "high-priority": "High",
    "medium-priority": "Medium",
    "low-priority": "Low",
    future: "Future",
    blocker: "Blocker",
    closed: "Closed",
  };
  document.querySelectorAll(".todo-state-btn").forEach(function (b) {
    var g = b.getAttribute("data-group");
    var label = LABELS[g] || g;
    var n = counts[g];
    b.innerHTML =
      escapeHtml(label) +
      (n != null ? ' <span class="todo-state-count">' + n + "</span>" : "");
  });
}

/* Viz lives inside the TODO tab and renders directly under the tab
 * header row — always visible at the top, with the grouped list below.
 * The previous segmented [Viz | List] toggle was removed per ywatanabe
 * (todo#82, 2026-04-19): viz should render "under the tab" and load
 * async so both are available without a mode switch. Skeleton paints
 * immediately; the SVG replaces it once the /api/todo/stats/ round-trip
 * completes (see viz-tab.js). */

document.addEventListener("DOMContentLoaded", function () {
  /* Viz is always visible — paint a skeleton right away so the tab
   * shell renders fast even before the stats round-trip finishes. */
  if (typeof renderVizTab === "function") renderVizTab();
  document.querySelectorAll(".todo-state-btn").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      var g = btn.getAttribute("data-group");
      var multi = e.ctrlKey || e.metaKey;
      if (multi) {
        /* Toggle this pill without affecting others; "all" is exclusive */
        if (g === "all") {
          todoActiveGroups = new Set(["all"]);
        } else {
          todoActiveGroups.delete("all");
          if (todoActiveGroups.has(g)) {
            todoActiveGroups.delete(g);
            if (todoActiveGroups.size === 0) todoActiveGroups.add("all");
          } else {
            todoActiveGroups.add(g);
          }
        }
      } else {
        /* Plain click — single select */
        todoActiveGroups = new Set([g]);
      }
      _syncTodoBtnState();
      fetchTodoList();
    });
  });
});

function _todoBackendState() {
  /* Load "all" from GitHub if "closed", "all", or "blocker" is in the active
   * set (blocker can match either open or closed issues). Otherwise just "open". */
  if (
    todoActiveGroups.has("all") ||
    todoActiveGroups.has("closed") ||
    todoActiveGroups.has("blocker")
  ) {
    return "all";
  }
  return "open";
}

/* Module-level cache so pill clicks don't re-hit the GitHub proxy.
 * Keyed by backend state ("all" vs "open"). A single "all" fetch is a
 * superset of "open", so once we have "all" we never need "open" again. */
var _todoCache = { all: null, open: null };
var _todoCacheTs = { all: 0, open: 0 };
var _TODO_CACHE_TTL_MS = 60 * 1000; // refetch at most once/min on pill clicks

function _hasBlockerLabel(issue) {
  return (issue.labels || []).some(function (l) {
    return (l.name || "").toLowerCase() === "blocker";
  });
}

function _passesGroupFilter(issue) {
  if (todoActiveGroups.has("all")) return true;
  /* Blocker pill — matches any issue (open or closed) carrying the blocker label */
  if (todoActiveGroups.has("blocker") && _hasBlockerLabel(issue)) return true;
  if (issue.state === "closed") {
    return todoActiveGroups.has("closed");
  }
  /* Open issue — must match a priority pill (closed-only selection hides all open) */
  var key = classifyIssue(issue);
  if (todoActiveGroups.has(key)) return true;
  /* _uncategorized shows under "all" only — unless "future" pill is active */
  if (key === "_uncategorized" && todoActiveGroups.has("future")) return true;
  return false;
}

function _populateIssueMap(issues) {
  _todoIssuesByNumber = {};
  (issues || []).forEach(function (i) {
    _todoIssuesByNumber[i.number] = i;
  });
}

function _updateLastFetchedLabel(ts) {
  var el = document.getElementById("todo-last-updated");
  if (!el) return;
  if (!ts) {
    el.textContent = "";
    return;
  }
  var d = new Date(ts);
  var hh = String(d.getHours()).padStart(2, "0");
  var mm = String(d.getMinutes()).padStart(2, "0");
  var ss = String(d.getSeconds()).padStart(2, "0");
  el.textContent = "Last updated: " + hh + ":" + mm + ":" + ss;
  el.setAttribute("data-ts", String(ts));
}

function _renderTodoFromCache(issues) {
  _populateIssueMap(issues);
  _updateTodoBtnCounts(issues || []);
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var container = document.getElementById("todo-grid");
  if (!issues || issues.length === 0) {
    container.innerHTML = '<p class="empty-notice">No issues</p>';
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try {
        msgInput.setSelectionRange(savedStart, savedEnd);
      } catch (_) {}
    }
    return;
  }

  /* Apply group filter */
  issues = issues.filter(_passesGroupFilter);
  if (issues.length === 0) {
    container.innerHTML =
      '<p class="empty-notice">No issues match the current filter</p>';
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try {
        msgInput.setSelectionRange(savedStart, savedEnd);
      } catch (_) {}
    }
    return;
  }

  var grouped = {};
  PRIORITY_GROUPS.forEach(function (g) {
    grouped[g.key] = [];
  });
  var closedGroup = [];
  issues.forEach(function (issue) {
    if (issue.state === "closed") {
      closedGroup.push(issue);
    } else {
      var key = classifyIssue(issue);
      grouped[key].push(issue);
    }
  });
  PRIORITY_GROUPS.forEach(function (g) {
    grouped[g.key].sort(sortByUpdated);
  });
  closedGroup.sort(sortByUpdated);

  var html = PRIORITY_GROUPS.map(function (g) {
    return buildGroupHtml(g, grouped[g.key]);
  }).join("");
  if (closedGroup.length > 0) {
    html += buildGroupHtml(
      { key: "closed", label: "Closed", color: "#555" },
      closedGroup,
    );
  }
  container.innerHTML = html;
  attachTodoEvents(container);
  _backgroundFillDetails(container);
  _updateLastFetchedLabel(_todoCacheTs.all || _todoCacheTs.open || Date.now());
  /* Re-apply any active filter-input query — the innerHTML rewrite above
   * wiped the display:none state runFilter() had previously set. Without
   * this, typing "todo#418" on the Chat tab then switching to TODO shows
   * every issue. */
  if (typeof runFilter === "function") runFilter();
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
}

async function fetchTodoList(forceRefresh) {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var _restoreFocus = function () {
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try {
        msgInput.setSelectionRange(savedStart, savedEnd);
      } catch (_) {}
    }
  };
  var state = _todoBackendState();
  var now = Date.now();

  /* Cache hit — render instantly with zero network. "all" superset also
   * satisfies any "open" request. */
  if (!forceRefresh) {
    if (_todoCache.all && now - _todoCacheTs.all < _TODO_CACHE_TTL_MS) {
      _renderTodoFromCache(_todoCache.all);
      return;
    }
    if (
      state === "open" &&
      _todoCache.open &&
      now - _todoCacheTs.open < _TODO_CACHE_TTL_MS
    ) {
      _renderTodoFromCache(_todoCache.open);
      return;
    }
  }

  try {
    var res = await fetch(
      "/api/github/issues?state=" + encodeURIComponent(state),
    );
    if (!res.ok) {
      console.error("Failed to fetch TODO list:", res.status);
      var errBody = {};
      try {
        errBody = await res.json();
      } catch (_) {}
      var msg = "Failed to load issues (HTTP " + res.status + ")";
      if (errBody.code === "missing_token") {
        msg =
          "Configure GITHUB_TOKEN in Docker environment to enable TODO list";
      } else if (errBody.error) {
        msg = errBody.error;
      }
      document.getElementById("todo-grid").innerHTML =
        '<p class="empty-notice">' + msg + "</p>";
      _restoreFocus();
      return;
    }
    var issues = await res.json();
    _todoCache[state] = issues;
    _todoCacheTs[state] = Date.now();
    _populateIssueMap(issues);
    _updateLastFetchedLabel(_todoCacheTs[state]);
    var container = document.getElementById("todo-grid");
    if (!issues || issues.length === 0) {
      container.innerHTML = '<p class="empty-notice">No issues</p>';
      _restoreFocus();
      return;
    }

    /* Apply group filter */
    issues = issues.filter(_passesGroupFilter);
    if (issues.length === 0) {
      container.innerHTML =
        '<p class="empty-notice">No issues match the current filter</p>';
      _restoreFocus();
      return;
    }

    /* Group and sort */
    var grouped = {};
    PRIORITY_GROUPS.forEach(function (g) {
      grouped[g.key] = [];
    });
    var closedGroup = [];
    issues.forEach(function (issue) {
      if (issue.state === "closed") {
        closedGroup.push(issue);
      } else {
        var key = classifyIssue(issue);
        grouped[key].push(issue);
      }
    });
    PRIORITY_GROUPS.forEach(function (g) {
      grouped[g.key].sort(sortByUpdated);
    });
    closedGroup.sort(sortByUpdated);

    var html = PRIORITY_GROUPS.map(function (g) {
      return buildGroupHtml(g, grouped[g.key]);
    }).join("");
    if (closedGroup.length > 0) {
      html += buildGroupHtml(
        { key: "closed", label: "Closed", color: "#555" },
        closedGroup,
      );
    }
    container.innerHTML = html;

    attachTodoEvents(container);
    _updateTodoBtnCounts(_todoCache[state] || []);
    _backgroundFillDetails(container);
    _restoreFocus();
  } catch (e) {
    console.error("TODO list fetch error:", e);
  }
}

function isLightColor(hex) {
  if (!hex || hex.length < 6) return false;
  var r = parseInt(hex.substring(0, 2), 16);
  var g = parseInt(hex.substring(2, 4), 16);
  var b = parseInt(hex.substring(4, 6), 16);
  var luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance > 0.5;
}

/* ================================================================== */
/* TODO stats dashboard (#171) — totals / burn-down / label breakdown  */
/* / by-repo / starvation. Backend: GET /api/todo/stats/ cached 60s.   */
/* ================================================================== */

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

function _renderTodoStatsByRepo(rows) {
  if (!rows || rows.length === 0) {
    return "";
  }
  var body = rows
    .map(function (r) {
      return (
        "<tr>" +
        "<td>" +
        escapeHtml(_shortRepo(r.repo)) +
        "</td>" +
        '<td class="todo-repo-num">' +
        (r.open || 0) +
        "</td>" +
        '<td class="todo-repo-num">' +
        (r.closed || 0) +
        "</td>" +
        "</tr>"
      );
    })
    .join("");
  return (
    '<div class="todo-stats-section">' +
    '<div class="todo-stats-h">By repo</div>' +
    '<table class="todo-repo-table">' +
    "<thead><tr><th>Repo</th><th>Open</th><th>Closed</th></tr></thead>" +
    "<tbody>" +
    body +
    "</tbody>" +
    "</table>" +
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
