/* TODO List -- GitHub Issues */
/* globals: escapeHtml */

async function fetchTodoList() {
  try {
    var res = await fetch("/api/github/issues");
    if (!res.ok) {
      console.error("Failed to fetch TODO list:", res.status);
      return;
    }
    var issues = await res.json();
    var container = document.getElementById("todo-grid");
    if (!issues || issues.length === 0) {
      container.innerHTML =
        '<p style="color:#555;font-size:11px;">No open issues</p>';
      return;
    }
    container.innerHTML = issues
      .map(function (issue) {
        var labelsHtml = "";
        if (issue.labels && issue.labels.length > 0) {
          labelsHtml = issue.labels
            .map(function (label) {
              var bg = label.color ? "#" + label.color : "#333";
              var fg = isLightColor(label.color || "333333") ? "#000" : "#fff";
              return (
                '<span class="todo-label" style="background:' +
                bg +
                ";color:" +
                fg +
                '">' +
                escapeHtml(label.name) +
                "</span>"
              );
            })
            .join("");
        }
        var assigneeHtml = "";
        if (issue.assignee && issue.assignee.login) {
          assigneeHtml =
            '<span class="todo-assignee">' +
            escapeHtml(issue.assignee.login) +
            "</span>";
        }
        return (
          '<a class="todo-item" href="' +
          escapeHtml(issue.html_url) +
          '" target="_blank" rel="noopener">' +
          '<span class="todo-number">#' +
          issue.number +
          "</span>" +
          '<span class="todo-title">' +
          escapeHtml(issue.title) +
          "</span>" +
          (labelsHtml
            ? '<div class="todo-labels">' + labelsHtml + "</div>"
            : "") +
          assigneeHtml +
          "</a>"
        );
      })
      .join("");
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
