// @ts-nocheck
import { apiUrl, escapeHtml } from "../app/utils";
import { renderSubtabs } from "./runner";

/* Releases tab — shared state, markdown renderer, and tracked-repos
 * networking helpers. Companion to releases-tab/runner.js, which drives
 * the UI. Loaded as a classic <script> before runner.js so the symbols
 * declared here are available when runner.js wires up the DOM.
 *
 * See releases-tab/runner.js for the full feature description.
 */
/* globals: apiUrl, escapeHtml, getCookie */

export var REPOS = []; // populated from /api/tracked-repos/

export var changelogCache = {}; // key "owner/repo" -> rendered HTML
var releasesInitialized = false;
var activeRepoKey = null;

/* ---------- Minimal markdown renderer (headers, lists, links, code,
 * bold/italic, paragraphs). Intentionally tiny — no new dependency. -------- */
export function renderMarkdown(md) {
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

export function _getCsrf() {
  if (typeof getCookie === "function") {
    var c = getCookie("csrftoken");
    if (c) return c;
  }
  var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

export function fetchTrackedRepos() {
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

export function persistOrder(ids) {
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

// Expose cross-file mutable state via globalThis:
(globalThis as any).activeRepoKey = (typeof activeRepoKey !== 'undefined' ? activeRepoKey : undefined);
(globalThis as any).releasesInitialized = (typeof releasesInitialized !== 'undefined' ? releasesInitialized : undefined);
