/* TODO tab list view — filter pills, view switcher, fetch + render */
/* globals: escapeHtml, runFilter, renderVizTab,
 *          PRIORITY_GROUPS, classifyIssue, sortByUpdated,
 *          attachTodoEvents, buildGroupHtml, _backgroundFillDetails,
 *          _todoIssuesByNumber */

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

/* View mode switcher for TODO tab ([ Viz | List ]). User requested
 * an explicit toggle so each mode gets the full canvas instead of
 * stacking both (todo#102). Default to List — the pills+grid is the
 * primary workflow; Viz is a periodic check. Persists in localStorage. */
var _TODO_VIEW_KEY = "orochi.todoViewMode";
function _todoViewMode() {
  try {
    var v = localStorage.getItem(_TODO_VIEW_KEY);
    return v === "viz" ? "viz" : "list";
  } catch (_) {
    return "list";
  }
}
function _applyTodoViewMode(mode) {
  var isViz = mode === "viz";
  var viz = document.getElementById("viz-content");
  var stats = document.getElementById("todo-stats");
  var grid = document.getElementById("todo-grid");
  var pills = document.querySelector("#todo-view .todo-state-filter");
  if (viz) viz.style.display = isViz ? "" : "none";
  if (stats) stats.style.display = isViz ? "none" : "";
  if (grid) grid.style.display = isViz ? "none" : "";
  if (pills) pills.style.display = isViz ? "none" : "";
  document
    .querySelectorAll("#todo-view [data-todo-view]")
    .forEach(function (btn) {
      btn.classList.toggle(
        "active",
        btn.getAttribute("data-todo-view") === mode,
      );
    });
  if (isViz && typeof renderVizTab === "function") renderVizTab();
}
function _wireTodoViewSwitch() {
  document
    .querySelectorAll("#todo-view [data-todo-view]")
    .forEach(function (btn) {
      btn.addEventListener("click", function () {
        var mode = btn.getAttribute("data-todo-view") || "list";
        try {
          localStorage.setItem(_TODO_VIEW_KEY, mode);
        } catch (_) {}
        _applyTodoViewMode(mode);
      });
    });
  _applyTodoViewMode(_todoViewMode());
}

document.addEventListener("DOMContentLoaded", function () {
  _wireTodoViewSwitch();
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
