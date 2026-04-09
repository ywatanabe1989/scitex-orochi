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

function truncateBody(text, max) {
  if (!text) return "(no description)";
  text = text.replace(/\r\n/g, "\n");
  if (text.length > max) return text.substring(0, max) + "...";
  return text;
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

function buildDetailHtml(issue) {
  var body = truncateBody(issue.body || "", 500);
  var assignee =
    issue.assignee && issue.assignee.login
      ? issue.assignee.login
      : "unassigned";
  return (
    '<div class="todo-detail">' +
    '<div class="todo-detail-body">' +
    escapeHtml(body) +
    "</div>" +
    '<div class="todo-detail-meta">' +
    "<span>Assignee: " +
    escapeHtml(assignee) +
    "</span>" +
    "<span>Created: " +
    formatDate(issue.created_at) +
    "</span>" +
    "<span>Updated: " +
    formatDate(issue.updated_at) +
    "</span>" +
    '<a href="' +
    escapeHtml(issue.html_url) +
    '" target="_blank" rel="noopener" class="todo-detail-link">' +
    "Open on GitHub" +
    "</a>" +
    "</div>" +
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
  return (
    '<div class="todo-item' + closedClass + '" data-issue-number="' +
    issue.number +
    '">' +
    '<div class="todo-item-row">' +
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
    buildDetailHtml(issue) +
    "</div>"
  );
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

/* Active filter groups — Set so Ctrl/Cmd-click can multi-select */
var todoActiveGroups = new Set(["all"]);

function _syncTodoBtnState() {
  document.querySelectorAll(".todo-state-btn").forEach(function (b) {
    var g = b.getAttribute("data-group");
    b.classList.toggle("active", todoActiveGroups.has(g));
  });
}

document.addEventListener("DOMContentLoaded", function () {
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
  /* Load "all" from GitHub if "closed" or "all" is in the active set, otherwise just "open". */
  if (todoActiveGroups.has("all") || todoActiveGroups.has("closed")) return "all";
  return "open";
}

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

async function fetchTodoList() {
  try {
    var res = await fetch("/api/github/issues?state=" + encodeURIComponent(_todoBackendState()));
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
      return;
    }
    var issues = await res.json();
    var container = document.getElementById("todo-grid");
    if (!issues || issues.length === 0) {
      container.innerHTML = '<p class="empty-notice">No issues</p>';
      return;
    }

    /* Apply group filter */
    issues = issues.filter(_passesGroupFilter);
    if (issues.length === 0) {
      container.innerHTML = '<p class="empty-notice">No issues match the current filter</p>';
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
