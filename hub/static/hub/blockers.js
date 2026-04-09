/* Blockers sidebar section — surface issues labelled "blocker" so agent
 * requests for user input don't drown in chat noise. */
/* globals: apiUrl, escapeHtml */

var _blockersRefreshTimer = null;
var _BLOCKERS_POLL_MS = 60 * 1000;

function _renderBlockersSidebar(issues) {
  var container = document.getElementById("blockers");
  var countEl = document.getElementById("sidebar-count-blockers");
  if (!container) return;
  var list = (issues || []).filter(function (i) {
    return (i.labels || []).some(function (l) {
      return (l.name || "").toLowerCase() === "blocker";
    });
  });
  if (countEl) countEl.textContent = list.length ? "(" + list.length + ")" : "";
  if (!list.length) {
    container.innerHTML = '<p class="blockers-empty">No blockers</p>';
    return;
  }
  container.innerHTML = list
    .map(function (i) {
      var assignee =
        i.assignee && i.assignee.login
          ? '<span class="blocker-assignee">@' + escapeHtml(i.assignee.login) + "</span>"
          : "";
      return (
        '<a class="blocker-item" href="' +
        escapeHtml(i.html_url || "#") +
        '" target="_blank" rel="noopener" title="' +
        escapeHtml(i.title || "") +
        '">' +
        '<span class="blocker-icon">⚠</span>' +
        '<span class="blocker-num">#' +
        i.number +
        "</span>" +
        '<span class="blocker-title">' +
        escapeHtml(i.title || "") +
        "</span>" +
        assignee +
        "</a>"
      );
    })
    .join("");
}

async function fetchBlockers() {
  try {
    var res = await fetch(
      apiUrl("/api/github/issues?state=open&labels=blocker"),
      { credentials: "same-origin" },
    );
    if (!res.ok) return;
    var data = await res.json();
    _renderBlockersSidebar(data);
  } catch (e) {
    /* silent */
  }
}

function startBlockersPoll() {
  fetchBlockers();
  if (_blockersRefreshTimer) return;
  _blockersRefreshTimer = setInterval(fetchBlockers, _BLOCKERS_POLL_MS);
}

document.addEventListener("DOMContentLoaded", startBlockersPoll);
