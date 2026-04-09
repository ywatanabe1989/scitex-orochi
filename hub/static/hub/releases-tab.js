/* Releases tab — git log based changelog for Orochi */
/* globals: apiUrl, escapeHtml, timeAgo */

var releasesCache = [];

function classifySubject(subject) {
  var s = (subject || "").toLowerCase();
  if (s.indexOf("fix") === 0 || s.indexOf("fix:") !== -1) return "fix";
  if (s.indexOf("feat") === 0 || s.indexOf("feat:") !== -1) return "feat";
  if (s.indexOf("refactor") === 0) return "refactor";
  if (s.indexOf("docs") === 0) return "docs";
  if (s.indexOf("test") === 0) return "test";
  if (s.indexOf("chore") === 0) return "chore";
  return "other";
}

function renderReleases() {
  var container = document.getElementById("releases-list");
  if (!container) return;
  if (releasesCache.length === 0) {
    container.innerHTML = '<p class="empty-notice">No release history available (git log unavailable in container).</p>';
    return;
  }
  container.innerHTML = releasesCache.map(function (r) {
    var kind = classifySubject(r.subject);
    var when = timeAgo(r.date) || r.date;
    var refs = r.refs ? ' <span class="release-refs">' + escapeHtml(r.refs) + '</span>' : '';
    var body = r.body ? '<div class="release-body">' + escapeHtml(r.body).replace(/\n/g, '<br>') + '</div>' : '';
    return (
      '<div class="release-item release-' + kind + '">' +
      '<div class="release-header">' +
      '<span class="release-kind release-kind-' + kind + '">' + kind + '</span>' +
      '<span class="release-subject">' + escapeHtml(r.subject) + '</span>' +
      refs +
      '</div>' +
      '<div class="release-meta">' +
      '<code class="release-sha">' + escapeHtml(r.short_sha) + '</code>' +
      ' &middot; ' + escapeHtml(r.author) +
      ' &middot; ' + escapeHtml(when) +
      '</div>' +
      body +
      '</div>'
    );
  }).join("");
}

async function fetchReleases() {
  try {
    var res = await fetch(apiUrl("/api/releases/"), { credentials: "same-origin" });
    if (!res.ok) {
      console.error("fetchReleases failed:", res.status);
      return;
    }
    releasesCache = await res.json();
    renderReleases();
  } catch (e) {
    console.warn("fetchReleases error:", e);
  }
}

document.addEventListener("DOMContentLoaded", function () {
  var tabBtn = document.querySelector('[data-tab="releases"]');
  if (tabBtn) {
    tabBtn.addEventListener("click", fetchReleases);
  }
});
