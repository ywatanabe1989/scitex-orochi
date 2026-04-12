/* Releases tab — per-repo CHANGELOG.md sub-tabs.
 *
 * UI mirrors the Settings tab sub-tab pattern (settings-mode-tabs):
 *   [ scitex-orochi ] [ scitex-cloud ] [ scitex-python ] [ scitex ] ...
 * The active sub-tab fetches CHANGELOG.md from
 *   GET /api/repo/<owner>/<repo>/changelog/
 * and renders it as HTML using a small built-in markdown renderer.
 *
 * The endpoint caches GitHub responses for 5 minutes server-side; we also
 * cache fetched markdown in-memory client-side so re-clicking a sub-tab is
 * instant and does not re-hit the network.
 */
/* globals: apiUrl, escapeHtml */

var REPOS = [
  { owner: "ywatanabe1989", repo: "scitex-orochi", label: "scitex-orochi" },
  { owner: "ywatanabe1989", repo: "scitex-cloud", label: "scitex-cloud" },
  { owner: "ywatanabe1989", repo: "scitex-python", label: "scitex-python" },
  { owner: "ywatanabe1989", repo: "scitex", label: "scitex" },
  {
    owner: "ywatanabe1989",
    repo: "scitex-agent-container",
    label: "scitex-agent-container",
  },
];

var changelogCache = {}; // key "owner/repo" -> rendered HTML
var releasesInitialized = false;
var activeRepoKey = null;

/* ---------- Minimal markdown renderer (headers, lists, links, code,
 * bold/italic, paragraphs). Intentionally tiny — no new dependency. -------- */
function renderMarkdown(md) {
  if (!md) return "";

  // Extract fenced code blocks first so their contents are not transformed.
  var codeBlocks = [];
  md = md.replace(/```([a-zA-Z0-9_+-]*)\n([\s\S]*?)```/g, function (_, lang, code) {
    var idx = codeBlocks.length;
    codeBlocks.push(
      '<pre class="md-code"><code>' + escapeHtml(code) + "</code></pre>",
    );
    return "\u0000CODEBLOCK" + idx + "\u0000";
  });

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

function renderSubtabs() {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var bar = document.getElementById("releases-subtabs");
  if (!bar) return;
  bar.innerHTML = REPOS.map(function (r) {
    var key = r.owner + "/" + r.repo;
    var cls =
      "settings-mode-btn releases-subtab-btn" +
      (key === activeRepoKey ? " active" : "");
    return (
      '<button type="button" class="' +
      cls +
      '" data-repo-key="' +
      escapeHtml(key) +
      '">' +
      escapeHtml(r.label) +
      "</button>"
    );
  }).join("");
  bar.querySelectorAll(".releases-subtab-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var key = btn.getAttribute("data-repo-key");
      selectRepo(key);
    });
  });
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
  }
}

function selectRepo(key) {
  activeRepoKey = key;
  var bar = document.getElementById("releases-subtabs");
  if (bar) {
    bar.querySelectorAll(".releases-subtab-btn").forEach(function (btn) {
      btn.classList.toggle(
        "active",
        btn.getAttribute("data-repo-key") === key,
      );
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
      try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
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
      } else if (r.status === 404 || (r.data && r.data.error && /404/.test(r.data.error))) {
        html =
          '<div class="empty-notice">' +
          '<p>📋 No <code>CHANGELOG.md</code> in this repository yet.</p>' +
          '<p style="opacity:0.7;font-size:13px;">' +
          'Add a <code>CHANGELOG.md</code> file to the repo root to populate this view. ' +
          'Format: <a href="https://keepachangelog.com/" target="_blank" rel="noopener">Keep a Changelog</a>.' +
          '</p></div>';
      } else {
        var msg =
          (r.data && r.data.error) ||
          "Failed to load CHANGELOG.md (status " + r.status + ")";
        html = '<p class="empty-notice">' + escapeHtml(msg) + "</p>";
      }
      content.innerHTML = html;
      if (_ihf && document.activeElement !== _mi) {
        _mi.focus();
        try { _mi.setSelectionRange(_ss, _se); } catch (_) {}
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
        try { _mi.setSelectionRange(_ss, _se); } catch (_) {}
      }
    });
}

function initReleasesTab() {
  if (releasesInitialized) return;
  releasesInitialized = true;
  activeRepoKey = REPOS[0].owner + "/" + REPOS[0].repo; // scitex-orochi default
  renderSubtabs();
  loadChangelog(activeRepoKey);
}

document.addEventListener("DOMContentLoaded", function () {
  var tabBtn = document.querySelector('[data-tab="releases"]');
  if (tabBtn) {
    tabBtn.addEventListener("click", initReleasesTab);
  }
});
