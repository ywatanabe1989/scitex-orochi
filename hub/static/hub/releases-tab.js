/* Releases tab — per-repo CHANGELOG.md sub-tabs with CRUD (todo#90).
 *
 * UI mirrors the Settings tab sub-tab pattern (settings-mode-tabs):
 *   [ scitex-orochi ] [ scitex-cloud ] ...  [+ Add Repo]
 * Each sub-tab also carries a small "×" delete control (revealed on
 * hover) so users can remove repos they no longer want to follow.
 *
 * The active sub-tab fetches CHANGELOG.md from
 *   GET /api/repo/<owner>/<repo>/changelog/
 * and renders it as HTML using a small built-in markdown renderer.
 *
 * The endpoint caches GitHub responses for 5 minutes server-side; we also
 * cache fetched markdown in-memory client-side so re-clicking a sub-tab is
 * instant and does not re-hit the network.
 *
 * Repo list is loaded from GET /api/tracked-repos/. Add via
 * POST /api/tracked-repos/ with `{url: "https://github.com/owner/repo"}`.
 * Delete via DELETE /api/tracked-repos/<id>/.
 */
/* globals: apiUrl, escapeHtml, getCookie */

var REPOS = []; // populated from /api/tracked-repos/

var changelogCache = {}; // key "owner/repo" -> rendered HTML
var releasesInitialized = false;
var activeRepoKey = null;

/* ---------- Minimal markdown renderer (headers, lists, links, code,
 * bold/italic, paragraphs). Intentionally tiny — no new dependency. -------- */
function renderMarkdown(md) {
  if (!md) return "";

  // Extract fenced code blocks first so their contents are not transformed.
  var codeBlocks = [];
  md = md.replace(
    /```([a-zA-Z0-9_+-]*)\n([\s\S]*?)```/g,
    function (_, lang, code) {
      var idx = codeBlocks.length;
      codeBlocks.push(
        '<pre class="md-code"><code>' + escapeHtml(code) + "</code></pre>",
      );
      return "\u0000CODEBLOCK" + idx + "\u0000";
    },
  );

  // Escape everything else, then re-introduce inline syntax.
  md = escapeHtml(md);

  // Headers
  md = md.replace(/^###### (.*)$/gm, "<h6>$1</h6>");
  md = md.replace(/^##### (.*)$/gm, "<h5>$1</h5>");
  md = md.replace(/^#### (.*)$/gm, "<h4>$1</h4>");
  md = md.replace(/^### (.*)$/gm, "<h3>$1</h3>");
  md = md.replace(/^## (.*)$/gm, "<h2>$1</h2>");
  md = md.replace(/^# (.*)$/gm, "<h1>$1</h1>");

  // Horizontal rule
  md = md.replace(/^\s*---\s*$/gm, "<hr>");

  // Inline code
  md = md.replace(/`([^`\n]+)`/g, '<code class="md-inline-code">$1</code>');

  // Bold + italic. Bold first to avoid clobbering by italic.
  md = md.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  md = md.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");

  // Links: [text](url)
  md = md.replace(
    /\[([^\]]+)\]\(([^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
  );

  // Lists. Group consecutive list lines into <ul>/<ol>.
  var lines = md.split("\n");
  var out = [];
  var listType = null; // 'ul' or 'ol'
  var paraBuf = [];

  function flushPara() {
    if (paraBuf.length) {
      var text = paraBuf.join(" ").trim();
      if (text) out.push("<p>" + text + "</p>");
      paraBuf = [];
    }
  }
  function flushList() {
    if (listType) {
      out.push("</" + listType + ">");
      listType = null;
    }
  }

  for (var i = 0; i < lines.length; i++) {
    var line = lines[i];
    var ulMatch = line.match(/^\s*[-*+]\s+(.*)$/);
    var olMatch = line.match(/^\s*\d+\.\s+(.*)$/);
    var blockMatch = line.match(/^<(h[1-6]|hr|pre|ul|ol|li|p|blockquote)/);

    if (ulMatch) {
      flushPara();
      if (listType !== "ul") {
        flushList();
        out.push("<ul>");
        listType = "ul";
      }
      out.push("<li>" + ulMatch[1] + "</li>");
    } else if (olMatch) {
      flushPara();
      if (listType !== "ol") {
        flushList();
        out.push("<ol>");
        listType = "ol";
      }
      out.push("<li>" + olMatch[1] + "</li>");
    } else if (line.trim() === "") {
      flushPara();
      flushList();
    } else if (blockMatch || line.indexOf("\u0000CODEBLOCK") !== -1) {
      flushPara();
      flushList();
      out.push(line);
    } else {
      paraBuf.push(line);
    }
  }
  flushPara();
  flushList();

  var html = out.join("\n");

  // Restore code blocks
  html = html.replace(/\u0000CODEBLOCK(\d+)\u0000/g, function (_, idx) {
    return codeBlocks[parseInt(idx, 10)];
  });

  return html;
}

function _getCsrf() {
  if (typeof getCookie === "function") {
    var c = getCookie("csrftoken");
    if (c) return c;
  }
  var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

function fetchTrackedRepos() {
  return fetch(apiUrl("/api/tracked-repos/"), {
    credentials: "same-origin",
  })
    .then(function (res) {
      return res.json().then(function (data) {
        return { ok: res.ok, status: res.status, data: data };
      });
    })
    .then(function (r) {
      if (r.ok && r.data && Array.isArray(r.data.repos)) {
        REPOS = r.data.repos.map(function (x) {
          return {
            id: x.id,
            owner: x.owner,
            repo: x.repo,
            label: x.label || x.repo,
          };
        });
      } else {
        REPOS = [];
      }
      return REPOS;
    })
    .catch(function () {
      REPOS = [];
      return REPOS;
    });
}

function renderSubtabs() {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var bar = document.getElementById("releases-subtabs");
  if (!bar) return;

  var tabsHtml = REPOS.map(function (r) {
    var key = r.owner + "/" + r.repo;
    var cls =
      "settings-mode-btn releases-subtab-btn" +
      (key === activeRepoKey ? " active" : "");
    // draggable on the wrapper so the delete "×" is hit-tested correctly
    // inside the drag region (todo#91). data-repo-id on the wrapper
    // identifies the row for reorder; mousedown on the "×" stops
    // propagation so clicking delete doesn't kick off a drag.
    return (
      '<span class="releases-subtab-wrap" draggable="true" ' +
      'data-repo-id="' +
      r.id +
      '" data-repo-key="' +
      escapeHtml(key) +
      '">' +
      '<button type="button" class="' +
      cls +
      '" data-repo-key="' +
      escapeHtml(key) +
      '">' +
      escapeHtml(r.label || r.repo) +
      "</button>" +
      '<button type="button" class="releases-subtab-del" ' +
      'data-repo-id="' +
      r.id +
      '" data-repo-key="' +
      escapeHtml(key) +
      '" title="Remove ' +
      escapeHtml(key) +
      '" aria-label="Remove ' +
      escapeHtml(key) +
      '">×</button>' +
      "</span>"
    );
  }).join("");

  tabsHtml +=
    '<button type="button" class="releases-add-btn" id="releases-add-btn" ' +
    'title="Track a new GitHub repo">+ Add Repo</button>';

  bar.innerHTML = tabsHtml;

  bar.querySelectorAll(".releases-subtab-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var key = btn.getAttribute("data-repo-key");
      selectRepo(key);
    });
  });
  bar.querySelectorAll(".releases-subtab-del").forEach(function (btn) {
    // Suppress drag when the user is reaching for the delete control.
    btn.addEventListener("mousedown", function (ev) {
      ev.stopPropagation();
    });
    btn.addEventListener("click", function (ev) {
      ev.stopPropagation();
      var id = btn.getAttribute("data-repo-id");
      var key = btn.getAttribute("data-repo-key");
      deleteRepo(id, key);
    });
  });
  bar.querySelectorAll(".releases-subtab-wrap").forEach(function (wrap) {
    attachDragHandlers(wrap);
  });
  var addBtn = bar.querySelector("#releases-add-btn");
  if (addBtn) {
    addBtn.addEventListener("click", openAddRepoDialog);
  }

  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
}

/* ---------- Drag-and-drop reorder (todo#91) -----------------------------
 * Vanilla HTML5 DnD on each ``.releases-subtab-wrap``. On ``dragstart``
 * we stash the row id in ``dataTransfer`` (plus an in-memory fallback
 * because Chrome blocks reads of the data payload during ``dragover``
 * for security reasons). On ``dragover`` we compute whether the cursor
 * is in the left or right half of the target and toggle the indicator
 * class accordingly, so the user gets a visible drop marker where the
 * dragged tab will land. On ``drop`` we reorder the DOM immediately
 * (optimistic update) and POST the new id order to the backend; if the
 * server reply disagrees we fall back to ``fetchTrackedRepos()`` and
 * ``renderSubtabs()`` to reconcile. ``dragend`` always cleans up the
 * visual state regardless of where the drop happened.
 * -------------------------------------------------------------------- */
var _dragSrcId = null;

function _clearDragIndicators() {
  var bar = document.getElementById("releases-subtabs");
  if (!bar) return;
  bar.querySelectorAll(".releases-subtab-wrap").forEach(function (w) {
    w.classList.remove("drag-over-before", "drag-over-after", "dragging");
  });
}

function attachDragHandlers(wrap) {
  wrap.addEventListener("dragstart", function (ev) {
    var id = wrap.getAttribute("data-repo-id");
    _dragSrcId = id;
    try {
      ev.dataTransfer.effectAllowed = "move";
      ev.dataTransfer.setData("text/plain", id);
    } catch (_) {
      // Some browsers block setData on drag events inside iframes; the
      // in-memory _dragSrcId is the source of truth either way.
    }
    wrap.classList.add("dragging");
  });

  wrap.addEventListener("dragover", function (ev) {
    if (_dragSrcId == null) return;
    var myId = wrap.getAttribute("data-repo-id");
    if (myId === _dragSrcId) return;
    ev.preventDefault();
    try {
      ev.dataTransfer.dropEffect = "move";
    } catch (_) {}
    var rect = wrap.getBoundingClientRect();
    var before = ev.clientX < rect.left + rect.width / 2;
    wrap.classList.toggle("drag-over-before", before);
    wrap.classList.toggle("drag-over-after", !before);
  });

  wrap.addEventListener("dragleave", function () {
    wrap.classList.remove("drag-over-before", "drag-over-after");
  });

  wrap.addEventListener("drop", function (ev) {
    ev.preventDefault();
    var srcId = _dragSrcId;
    _clearDragIndicators();
    if (!srcId || srcId === wrap.getAttribute("data-repo-id")) return;

    var bar = document.getElementById("releases-subtabs");
    if (!bar) return;
    var srcWrap = bar.querySelector(
      '.releases-subtab-wrap[data-repo-id="' + srcId + '"]',
    );
    if (!srcWrap) return;

    var rect = wrap.getBoundingClientRect();
    var insertBefore = ev.clientX < rect.left + rect.width / 2;
    if (insertBefore) {
      wrap.parentNode.insertBefore(srcWrap, wrap);
    } else if (wrap.nextSibling) {
      wrap.parentNode.insertBefore(srcWrap, wrap.nextSibling);
    } else {
      wrap.parentNode.appendChild(srcWrap);
    }

    // Collect new id order straight from the DOM (excludes the Add
    // button because it has no data-repo-id).
    var ids = [];
    bar.querySelectorAll(".releases-subtab-wrap").forEach(function (w) {
      var id = parseInt(w.getAttribute("data-repo-id"), 10);
      if (!isNaN(id)) ids.push(id);
    });
    persistOrder(ids);
  });

  wrap.addEventListener("dragend", function () {
    _dragSrcId = null;
    _clearDragIndicators();
  });
}

function persistOrder(ids) {
  fetch(apiUrl("/api/tracked-repos/reorder/"), {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": _getCsrf(),
    },
    body: JSON.stringify({ ids: ids }),
  })
    .then(function (res) {
      return res.json().then(function (data) {
        return { ok: res.ok, status: res.status, data: data };
      });
    })
    .then(function (r) {
      if (!r.ok) {
        window.alert(
          "Failed to save new order: " +
            ((r.data && r.data.error) || "HTTP " + r.status),
        );
        // Resync from the server to undo the optimistic DOM shuffle.
        return fetchTrackedRepos().then(renderSubtabs);
      }
      if (r.data && Array.isArray(r.data.repos)) {
        REPOS = r.data.repos.map(function (x) {
          return {
            id: x.id,
            owner: x.owner,
            repo: x.repo,
            label: x.label || x.repo,
          };
        });
      }
    })
    .catch(function () {
      // Network blip — resync from server so the UI doesn't lie.
      return fetchTrackedRepos().then(renderSubtabs);
    });
}

function openAddRepoDialog() {
  var url = window.prompt(
    "Add a GitHub repo to the Releases tab.\n\n" +
      "Enter a GitHub URL or 'owner/repo':",
    "https://github.com/",
  );
  if (!url) return;
  url = url.trim();
  if (!url || url === "https://github.com/") return;

  fetch(apiUrl("/api/tracked-repos/"), {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": _getCsrf(),
    },
    body: JSON.stringify({ url: url }),
  })
    .then(function (res) {
      return res.json().then(function (data) {
        return { ok: res.ok, status: res.status, data: data };
      });
    })
    .then(function (r) {
      if (!r.ok) {
        window.alert(
          "Failed to add repo: " +
            ((r.data && r.data.error) || "HTTP " + r.status),
        );
        return;
      }
      return fetchTrackedRepos().then(function () {
        if (r.data && r.data.repo) {
          activeRepoKey = r.data.repo.key;
        }
        renderSubtabs();
        if (activeRepoKey) loadChangelog(activeRepoKey);
      });
    })
    .catch(function (e) {
      window.alert("Network error: " + e);
    });
}

function deleteRepo(id, key) {
  if (!id) return;
  if (!window.confirm("Remove " + key + " from the Releases tab?")) return;

  fetch(apiUrl("/api/tracked-repos/" + id + "/"), {
    method: "DELETE",
    credentials: "same-origin",
    headers: {
      "X-CSRFToken": _getCsrf(),
    },
  })
    .then(function (res) {
      return res.json().then(function (data) {
        return { ok: res.ok, status: res.status, data: data };
      });
    })
    .then(function (r) {
      if (!r.ok) {
        window.alert(
          "Failed to remove repo: " +
            ((r.data && r.data.error) || "HTTP " + r.status),
        );
        return;
      }
      delete changelogCache[key];
      if (activeRepoKey === key) activeRepoKey = null;
      return fetchTrackedRepos().then(function () {
        if (!activeRepoKey && REPOS.length) {
          activeRepoKey = REPOS[0].owner + "/" + REPOS[0].repo;
        }
        renderSubtabs();
        var content = document.getElementById("releases-content");
        if (activeRepoKey) {
          loadChangelog(activeRepoKey);
        } else if (content) {
          content.innerHTML =
            '<p class="empty-notice">No tracked repos. Click "+ Add Repo" to track a GitHub repository.</p>';
        }
      });
    })
    .catch(function (e) {
      window.alert("Network error: " + e);
    });
}

function selectRepo(key) {
  activeRepoKey = key;
  var bar = document.getElementById("releases-subtabs");
  if (bar) {
    bar.querySelectorAll(".releases-subtab-btn").forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-repo-key") === key);
    });
  }
  loadChangelog(key);
}

function loadChangelog(key) {
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
  var content = document.getElementById("releases-content");
  if (!content) return;

  if (changelogCache[key]) {
    content.innerHTML = changelogCache[key];
    _restoreFocus();
    return;
  }

  content.innerHTML =
    '<div class="changelog-loading">Loading CHANGELOG.md…</div>';
  _restoreFocus();

  var parts = key.split("/");
  var owner = parts[0];
  var repo = parts[1];
  fetch(apiUrl("/api/repo/" + owner + "/" + repo + "/changelog/"), {
    credentials: "same-origin",
  })
    .then(function (res) {
      return res.json().then(function (data) {
        return { ok: res.ok, status: res.status, data: data };
      });
    })
    .then(function (r) {
      if (key !== activeRepoKey) return; // user switched away
      var _mi = document.getElementById("msg-input");
      var _ihf = _mi && document.activeElement === _mi;
      var _ss = _ihf ? _mi.selectionStart : 0;
      var _se = _ihf ? _mi.selectionEnd : 0;
      var html;
      if (r.ok && r.data && typeof r.data.content === "string") {
        var url = r.data.html_url || "";
        var header = url
          ? '<div class="changelog-source"><a href="' +
            escapeHtml(url) +
            '" target="_blank" rel="noopener noreferrer">View on GitHub</a></div>'
          : "";
        html =
          header +
          '<div class="changelog-rendered">' +
          renderMarkdown(r.data.content) +
          "</div>";
        changelogCache[key] = html;
      } else if (
        r.status === 404 ||
        (r.data && r.data.error && /404/.test(r.data.error))
      ) {
        html =
          '<div class="empty-notice">' +
          "<p>📋 No <code>CHANGELOG.md</code> in this repository yet.</p>" +
          '<p style="opacity:0.7;font-size:13px;">' +
          "Add a <code>CHANGELOG.md</code> file to the repo root to populate this view. " +
          'Format: <a href="https://keepachangelog.com/" target="_blank" rel="noopener">Keep a Changelog</a>.' +
          "</p></div>";
      } else {
        var msg =
          (r.data && r.data.error) ||
          "Failed to load CHANGELOG.md (status " + r.status + ")";
        html = '<p class="empty-notice">' + escapeHtml(msg) + "</p>";
      }
      content.innerHTML = html;
      if (_ihf && document.activeElement !== _mi) {
        _mi.focus();
        try {
          _mi.setSelectionRange(_ss, _se);
        } catch (_) {}
      }
    })
    .catch(function (e) {
      if (key !== activeRepoKey) return;
      var _mi = document.getElementById("msg-input");
      var _ihf = _mi && document.activeElement === _mi;
      var _ss = _ihf ? _mi.selectionStart : 0;
      var _se = _ihf ? _mi.selectionEnd : 0;
      content.innerHTML =
        '<p class="empty-notice">Network error: ' +
        escapeHtml(String(e)) +
        "</p>";
      if (_ihf && document.activeElement !== _mi) {
        _mi.focus();
        try {
          _mi.setSelectionRange(_ss, _se);
        } catch (_) {}
      }
    });
}

function initReleasesTab() {
  if (releasesInitialized) return;
  releasesInitialized = true;
  fetchTrackedRepos().then(function () {
    if (REPOS.length) {
      activeRepoKey = REPOS[0].owner + "/" + REPOS[0].repo;
    }
    renderSubtabs();
    var content = document.getElementById("releases-content");
    if (activeRepoKey) {
      loadChangelog(activeRepoKey);
    } else if (content) {
      content.innerHTML =
        '<p class="empty-notice">No tracked repos. Click "+ Add Repo" to track a GitHub repository.</p>';
    }
  });
}

document.addEventListener("DOMContentLoaded", function () {
  var tabBtn = document.querySelector('[data-tab="releases"]');
  if (tabBtn) {
    tabBtn.addEventListener("click", initReleasesTab);
  }
});
