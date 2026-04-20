// @ts-nocheck
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
