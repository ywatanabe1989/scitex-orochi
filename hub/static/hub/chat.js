/* Chat module -- message display, history, filtering */
/* globals: escapeHtml, getAgentColor, timeAgo, cachedAgentNames, userName,
   currentChannel, knownMessageKeys, messageKey, sendOrochiMessage,
   updateResourcePanel, token, apiUrl */

/* Voice-recording deferred message queue.
 * When window.isVoiceRecording is true, appendMessage defers the DOM update
 * here instead of immediately mutating the feed. The voice-input module calls
 * window._flushVoiceQueue() when recording stops, which drains the queue. */
var _voiceDeferQueue = [];
window._flushVoiceQueue = function () {
  var queued = _voiceDeferQueue.splice(0);
  queued.forEach(function (msg) { appendMessage(msg); });
};

function isKnownAgent(name) {
  return cachedAgentNames.indexOf(name) !== -1;
}

/* Cache of GitHub issue titles.
 *   issueTitleCache[number]            → title for the default repo
 *                                        (ywatanabe1989/todo, legacy `#N`)
 *   issueTitleCache["owner/repo#N"]    → title for cross-repo references
 * Negative lookups are stored as the literal string "" so we stop retrying
 * missing issues on every render pass. */
var issueTitleCache = {};
var issueTitleInflight = {};

function _hydrateIssueLink(a, title) {
  if (!title || a.dataset.hinted) return;
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var label = a.getAttribute("data-issue-label") || a.textContent;
  a.title = label + " " + title;
  a.innerHTML =
    escapeHtml(label) +
    ' <span class="issue-link-title">(' +
    escapeHtml(title) +
    ")</span>";
  a.dataset.hinted = "1";
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
  }
}

function _fetchCrossRepoTitle(repo, num, cb) {
  var key = repo + "#" + num;
  if (issueTitleCache[key] !== undefined) {
    cb(issueTitleCache[key] || null);
    return;
  }
  if (issueTitleInflight[key]) return;
  issueTitleInflight[key] = true;
  /* Build the path with query params first, then let apiUrl() add
   * '&token=' (it detects the existing '?' and chooses '&'). The previous
   * version concatenated '?repo=' AFTER apiUrl had already appended
   * '?token=', producing a malformed '?token=...?repo=...' URL → 400. */
  var url = apiUrl(
    "/api/github/issue-title?repo=" +
    encodeURIComponent(repo) +
    "&number=" +
    encodeURIComponent(num)
  );
  fetch(url, { credentials: "same-origin" })
    .then(function (r) {
      return r.ok ? r.json() : null;
    })
    .then(function (data) {
      delete issueTitleInflight[key];
      var title = (data && data.title) || "";
      issueTitleCache[key] = title;
      if (title) cb(title);
    })
    .catch(function () {
      delete issueTitleInflight[key];
    });
}

function applyIssueTitleHints(scope) {
  var root = scope || document;
  root.querySelectorAll(".issue-link").forEach(function (a) {
    if (a.dataset.hinted) return;
    var repo = a.getAttribute("data-issue-repo");
    var num = a.getAttribute("data-issue-num");
    if (!num) {
      var m = a.textContent.match(/#(\d+)/);
      if (!m) return;
      num = m[1];
      a.setAttribute("data-issue-num", num);
    }
    if (repo) {
      /* Cross-repo: hit the per-issue endpoint lazily. */
      var key = repo + "#" + num;
      var cached = issueTitleCache[key];
      if (cached) {
        _hydrateIssueLink(a, cached);
      } else if (cached === undefined) {
        _fetchCrossRepoTitle(repo, num, function (title) {
          _hydrateIssueLink(a, title);
        });
      }
    } else {
      /* Legacy bare `#N` → ywatanabe1989/todo, served from the list cache. */
      var title = issueTitleCache[num];
      if (title) _hydrateIssueLink(a, title);
    }
  });
}

async function refreshIssueTitleCache() {
  try {
    var res = await fetch(apiUrl("/api/github/issues"), {
      credentials: "same-origin",
    });
    if (!res.ok) return;
    var issues = await res.json();
    if (Array.isArray(issues)) {
      issues.forEach(function (i) {
        if (i && i.number && i.title)
          issueTitleCache[String(i.number)] = i.title;
      });
      applyIssueTitleHints();
    }
  } catch (e) {
    /* ignore */
  }
}
/* Refresh on load and every 2 minutes */
refreshIssueTitleCache();
setInterval(refreshIssueTitleCache, 120000);

function appendSystemMessage(msg) {
  var el = document.createElement("div");
  el.className = "msg msg-system";
  var ts = "";
  if (msg.ts) {
    var d = new Date(msg.ts);
    if (!isNaN(d.getTime())) {
      ts = timeAgo(msg.ts);
    }
  }
  var text = msg.text || "";
  el.innerHTML =
    '<div class="msg-system-content">' +
    '<span class="msg-system-icon">\u2022</span> ' +
    '<span class="msg-system-text">' +
    escapeHtml(text) +
    "</span>" +
    (ts ? ' <span class="ts">' + ts + "</span>" : "") +
    "</div>";
  var container = document.getElementById("messages");
  var nearBottom =
    container.scrollHeight - container.scrollTop - container.clientHeight < 150;
  /* Mirror appendMessage's focus/scroll guard — see todo#225/#227. */
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  container.appendChild(el);
  if (nearBottom) {
    container.scrollTop = container.scrollHeight;
  }
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
  }
}

/* Jump to a referenced message by opening its thread panel (msg#9641 / #362).
 * Correct spec per ywatanabe msg#9644: clicking msg#NNNN opens thread panel,
 * does NOT scroll the feed. Falls back to flash-in-place if threads.js
 * not loaded yet. */
function jumpToMsg(id) {
  if (typeof openThreadForMessage === "function") {
    openThreadForMessage(String(id));
    return;
  }
  /* Fallback: scroll + flash in feed */
  var el = document.querySelector('[data-msg-id="' + id + '"]');
  if (!el) return;
  var container = document.getElementById("messages");
  if (container) {
    var top = el.offsetTop - container.clientHeight / 2 + el.offsetHeight / 2;
    container.scrollTop = Math.max(0, top);
  }
  el.classList.add("msg-highlight");
  setTimeout(function () { el.classList.remove("msg-highlight"); }, 2000);
}

/* Shared attachment renderer — used by both the main feed and thread panel.
 * Returns an HTML string for all attachments in the array. */
function buildAttachmentsHtml(attachments) {
  var html = "";
  if (!attachments || !attachments.length) return html;
  var imageAttachments = attachments.filter(function (att) {
    return att.mime_type && att.mime_type.startsWith("image/") && att.url;
  });
  var imgCount = imageAttachments.length;
  var gridClass = imgCount <= 1 ? "count-1" : imgCount === 2 ? "count-2" : imgCount === 3 ? "count-3" : "count-many";
  var imagesHtml = "";
  imageAttachments.forEach(function (att) {
    imagesHtml += '<div class="attachment-img"><a href="' + escapeHtml(att.url) + '" target="_blank">' +
      '<img src="' + escapeHtml(att.url) + '" alt="' + escapeHtml(att.filename || "image") + '" loading="lazy"></a></div>';
  });
  if (imgCount > 0) html += '<div class="attachment-grid ' + gridClass + '">' + imagesHtml + "</div>";
  attachments.forEach(function (att) {
    if (!att.url) return;
    var mime = att.mime_type || "";
    var fname = att.filename || "attachment";
    var url = att.url;
    if (mime.indexOf("image/") === 0) return; /* handled in grid */
    var sizeStr = att.size ? (att.size > 1024 * 1024 ? (att.size / 1024 / 1024).toFixed(1) + " MB" : (att.size / 1024).toFixed(0) + " KB") : "";
    var ext = (fname.split(".").pop() || "").toLowerCase();
    var isMarkdown = mime === "text/markdown" || ext === "md" || ext === "markdown";
    var isText = mime.indexOf("text/") === 0 || mime === "application/json" ||
      ext === "txt" || ext === "log" || ext === "py" || ext === "json" ||
      ext === "yaml" || ext === "yml" || ext === "toml" || ext === "sh";
    var isPdf = mime === "application/pdf" || ext === "pdf";
    var isVideo = mime.indexOf("video/") === 0;
    var isAudio = mime.indexOf("audio/") === 0;
    if (isVideo) {
      html += '<div class="attachment-video"><video src="' + escapeHtml(url) + '" controls preload="metadata" style="max-width:100%"></video>' +
        '<div class="attachment-caption">' + escapeHtml(fname) + (sizeStr ? " · " + escapeHtml(sizeStr) : "") + '</div></div>';
      return;
    }
    if (isAudio) {
      html += '<div class="attachment-audio"><audio src="' + escapeHtml(url) + '" controls preload="metadata" style="max-width:100%"></audio>' +
        '<div class="attachment-caption">' + escapeHtml(fname) + (sizeStr ? " · " + escapeHtml(sizeStr) : "") + '</div></div>';
      return;
    }
    if (isPdf) {
      html += '<div class="attachment-card attachment-card-pdf" onclick="event.preventDefault();event.stopPropagation();' +
        'if(typeof openPdfViewer===\'function\')openPdfViewer(' + JSON.stringify(url).replace(/"/g, "&quot;") + ',' + JSON.stringify(fname).replace(/"/g, "&quot;") +
        ');else window.open(' + JSON.stringify(url).replace(/"/g, "&quot;") + ',\'_blank\')">' +
        '<div class="attachment-card-icon">PDF</div>' +
        '<div class="attachment-card-meta"><div class="attachment-card-name">' + escapeHtml(fname) + '</div>' +
        (sizeStr ? '<div class="attachment-card-size">' + escapeHtml(sizeStr) + '</div>' : '') + '</div></div>';
      return;
    }
    if (isMarkdown || isText) {
      var previewId = "att-prev-" + Math.random().toString(36).slice(2, 10);
      html += '<div class="attachment-card attachment-card-text' + (isMarkdown ? " attachment-card-md" : "") + '">' +
        '<div class="attachment-card-header"><a href="' + escapeHtml(url) + '" target="_blank" download class="attachment-card-name">' +
        escapeHtml(fname) + "</a>" + (sizeStr ? '<span class="attachment-card-size">' + escapeHtml(sizeStr) + '</span>' : '') + '</div>' +
        '<pre class="attachment-card-preview" id="' + previewId + '">\u2026 loading preview \u2026</pre></div>';
      setTimeout(function () {
        var pre = document.getElementById(previewId);
        if (!pre) return;
        fetch(url, { credentials: "same-origin" }).then(function (r) {
          if (!r.ok) throw new Error("preview fetch " + r.status);
          return r.text();
        }).then(function (text) {
          var p = document.getElementById(previewId);
          if (!p) return;
          var snippet = (text || "").slice(0, 1200);
          if (text.length > 1200) snippet += "\n\u2026";
          p.textContent = snippet;
        }).catch(function (_) {
          var p = document.getElementById(previewId);
          if (p) p.textContent = "(preview unavailable)";
        });
      }, 0);
      return;
    }
    html += '<div class="attachment-file"><a href="' + escapeHtml(url) + '" target="_blank" download>' +
      "\uD83D\uDCCE " + escapeHtml(fname) + (sizeStr ? " (" + escapeHtml(sizeStr) + ")" : "") + "</a></div>";
  });
  return html;
}

/* Render unprocessed mermaid diagrams within a given root element.
 * Calls mermaid.run() then wraps each rendered SVG as a blob-URL <img>
 * so that right-click Save/Copy works natively (scitex-orochi#165). */
function _renderMermaidIn(root) {
  if (typeof window.mermaid === 'undefined') return;
  var nodes = (root || document).querySelectorAll('.mermaid-rendered:not([data-mermaid-processed])');
  if (!nodes.length) return;
  nodes.forEach(function(n) { n.setAttribute('data-mermaid-processed', '1'); });
  var promise;
  try {
    promise = window.mermaid.run({ nodes: nodes });
  } catch (e) {
    /* Non-fatal: diagram parse error shows in the rendered div */
    return;
  }
  /* After render completes, convert SVG elements to blob-URL <img> tags
   * so that right-click "Save image" / "Copy image" works natively. */
  if (promise && typeof promise.then === 'function') {
    promise.then(function() {
      nodes.forEach(function(n) { _mermaidSvgToImg(n); });
    }).catch(function() { /* parse errors: leave div as-is */ });
  } else {
    /* Synchronous fallback (older mermaid builds) */
    setTimeout(function() {
      nodes.forEach(function(n) { _mermaidSvgToImg(n); });
    }, 100);
  }
}

/* Serialize the SVG rendered inside a .mermaid-rendered div to a blob URL,
 * replace the SVG with a responsive <img> (enables native right-click Save/Copy),
 * and wire click-to-enlarge via the existing files-tab lightbox.
 * scitex-orochi#165 */
function _mermaidSvgToImg(container) {
  var svgEl = container.querySelector('svg');
  if (!svgEl) return; /* parse error — no SVG was produced */

  /* Ensure the SVG namespace is set so XMLSerializer produces valid SVG */
  if (!svgEl.getAttribute('xmlns')) {
    svgEl.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  }

  var svgStr = new XMLSerializer().serializeToString(svgEl);
  var blob = new Blob([svgStr], { type: 'image/svg+xml' });
  var url = URL.createObjectURL(blob);

  var img = document.createElement('img');
  img.src = url;
  img.alt = 'Mermaid diagram';
  img.className = 'mermaid-img';

  /* Replace inline SVG with <img>; blob URL stays alive so right-click Save works */
  svgEl.parentNode.replaceChild(img, svgEl);

  /* Click-to-enlarge: open in the existing image lightbox (files-tab.js openImgViewer) */
  container.addEventListener('click', function(e) {
    if (e.target.closest('.mermaid-toggle')) return;
    if (typeof openImgViewer === 'function') {
      openImgViewer(url, 'mermaid-diagram.svg', [{ url: url, filename: 'mermaid-diagram.svg' }]);
    }
  });
}

function appendMessage(msg) {
  /* Filter hub-internal system messages from the feed (msg#10315).
   * Hub sends mention_reply messages (sender="hub") as status responses
   * when agents are @mentioned. These are noisy in regular channels. */
  var _meta = (msg.metadata || {});
  if (msg.sender === "hub" && _meta.source === "mention_reply") return;

  /* Voice-recording guard: defer the DOM update to avoid interrupting the
   * Web Speech API SpeechRecognition session. Scroll and layout changes
   * during active recording can cause the browser to abort recognition.
   * The queue is flushed by _flushVoiceQueue() when recording stops. */
  if (window.isVoiceRecording) {
    _voiceDeferQueue.push(msg);
    return;
  }
  var el = document.createElement("div");
  var senderName = msg.sender || "unknown";
  var isAgent = msg.sender_type === "agent" || isKnownAgent(senderName);
  el.className = "msg" + (isAgent ? "" : " msg-human");
  if (msg.id) el.setAttribute("data-msg-id", String(msg.id));
  /* todo#274 Part 2: tag sender for multi-select AND filter */
  el.setAttribute("data-sender", senderName);
  var ts = "";
  var fullTs = "";
  if (msg.ts) {
    var d = new Date(msg.ts);
    if (!isNaN(d.getTime())) {
      ts = timeAgo(msg.ts);
      fullTs = d.toLocaleString();
    }
  }
  var channel = (msg.payload && msg.payload.channel) || "";
  var content = "";
  if (msg.payload) {
    content =
      msg.payload.content || msg.payload.text || msg.payload.message || "";
  }
  /* Fallback to top-level fields (WebSocket flat format) */
  if (!content) {
    content = msg.text || msg.content || "";
  }
  /* Intercept resource reports */
  var meta = (msg.payload && msg.payload.metadata) || {};
  if (meta.type === "resource_report" && meta.data) {
    updateResourcePanel(meta.data);
  }
  /* Allow attachment-only messages (empty text with images/files) */
  var attachments =
    (msg.payload && msg.payload.attachments) ||
    (msg.metadata && msg.metadata.attachments) ||
    msg.attachments ||
    [];
  if (!content && attachments.length === 0) return;
  var senderColor = getResolvedAgentColor(senderName);
  if (channel) {
    el.setAttribute("data-channel", channel);
  }
  /* Mentions must be highlighted BEFORE the newline→<br> conversion,
   * otherwise a mention sitting right after a line break doesn't match
   * the `(^|[\s])` anchor (since <br> is not whitespace). */
  var escaped = escapeHtml(content);

  /* Fenced code blocks: ```lang\n...\n``` — extract BEFORE inline processing
   * so the inline-code regex and \n→<br> don't corrupt their content. (#375)
   * Placeholder: NUL-delimited tokens replaced after all inline processing. */
  var _codeBlocks = [];
  escaped = escaped.replace(
    /```([\w.+-]*)[ \t]*\n([\s\S]*?)```/g,
    function (_, lang, code) {
      var trimmed = code.replace(/\n$/, "");
      var html;
      if (lang && lang.toLowerCase() === 'mermaid') {
        /* Mermaid diagrams: render as SVG inline with a raw-script toggle */
        html =
          '<div class="mermaid-container">' +
          '<div class="mermaid-rendered">' + trimmed + '</div>' +
          '<pre class="mermaid-raw" style="display:none"><code>' + trimmed + '</code></pre>' +
          '<button class="mermaid-toggle">Show raw</button>' +
          '</div>';
      } else {
        var hljsCls = lang ? ' class="language-' + lang + '"' : "";
        var langBadge = lang
          ? '<span class="code-lang-badge">' + escapeHtml(lang) + '</span>'
          : "";
        html =
          '<div class="code-block-wrap">' + langBadge +
          '<pre class="code-block"><code' + hljsCls + ">" + trimmed + "</code></pre></div>";
      }
      _codeBlocks.push(html);
      return "\x00" + (_codeBlocks.length - 1) + "\x00";
    }
  );

  /* Blockquote: lines beginning with `> ` (rendered as &gt; after escaping).
   * Process before inline markup so block structure is resolved first. (#9721) */
  escaped = (function _blockquote(s) {
    var lines = s.split("\n");
    var out = [];
    var i = 0;
    while (i < lines.length) {
      if (/^&gt;\s?/.test(lines[i])) {
        var block = [];
        while (i < lines.length && /^&gt;\s?/.test(lines[i])) {
          block.push(lines[i].replace(/^&gt;\s?/, ""));
          i++;
        }
        out.push('<blockquote class="chat-blockquote">' + block.join("\n") + "</blockquote>");
      } else {
        out.push(lines[i]);
        i++;
      }
    }
    return out.join("\n");
  })(escaped);

  /* Bare-name mentions: highlight the known agent/member names even when
   * they appear without a leading @. Kept conservative by requiring the
   * name to be sourced from cachedAgentNames/cachedMemberNames and by
   * using word boundaries so substrings inside other words don't match. */
  function _highlightBareNames(s) {
    var names = [];
    if (
      typeof cachedAgentNames !== "undefined" &&
      Array.isArray(cachedAgentNames)
    ) {
      names = names.concat(cachedAgentNames);
    }
    if (
      typeof cachedMemberNames !== "undefined" &&
      Array.isArray(cachedMemberNames)
    ) {
      names = names.concat(cachedMemberNames);
    }
    /* Dedup + longest-first so "head@mba" wins over "head" */
    names = Array.from(new Set(names)).filter(Boolean);
    names.sort(function (a, b) {
      return b.length - a.length;
    });
    names.forEach(function (n) {
      if (!n || n.length < 2) return;
      var escName = n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      /* Skip if already inside a mention-highlight span */
      var re = new RegExp("(^|[^\\w@>])" + escName + "(?![\\w@.-])", "g");
      s = s.replace(re, function (match, lead, offset, full) {
        /* Don't double-wrap if the match is already within an existing
         * <span class="mention-highlight">…</span>. Cheap scan backwards. */
        var before = full.slice(0, offset + lead.length);
        var lastOpen = before.lastIndexOf("<span");
        var lastClose = before.lastIndexOf("</span>");
        if (lastOpen > lastClose) return match;
        return lead + '<span class="mention-highlight">' + n + "</span>";
      });
    });
    return s;
  }

  /* Group mention tokens (@heads, @healers, @mambas, @all, @agents) get a
   * distinct chip class with a tooltip describing who the group expands to.
   * Kept in sync with hub/consumers.py GROUP_PATTERNS (todo#421). */
  var MENTION_GROUP_TOKENS = {
    heads: "all head-* agents",
    healers: "all mamba-healer-* agents",
    mambas: "all mamba-* agents",
    all: "everyone in the workspace",
    agents: "all agents in the workspace",
  };

  /* Return true if the character at index `idx` of `src` sits inside a
   * single-line `...` inline-code span. Counts backticks from the start
   * of the current line; odd count == inside. Used to suppress mention
   * highlighting for @tokens that live inside backticks (todo#421). */
  function _isInsideInlineCode(src, idx) {
    var lineStart = src.lastIndexOf("\n", idx - 1) + 1;
    var ticks = 0;
    for (var i = lineStart; i < idx; i++) {
      if (src.charCodeAt(i) === 96 /* ` */) ticks++;
    }
    return (ticks % 2) === 1;
  }

  /* Match @ after any non-word char so CJK text like「こんにちは@mamba」highlights (#9958) */
  var highlightedContent = escaped.replace(
    /(^|[^\w])@([\w@.\-]+)/g,
    function (match, prefix, name, offset, full) {
      /* Suppress chip/highlight if we are inside an inline `code` span.
       * Fenced ```blocks``` are already replaced with NUL placeholders
       * above, so this guard only needs to worry about backticks. */
      if (_isInsideInlineCode(full, offset + prefix.length)) {
        return match;
      }
      var desc = MENTION_GROUP_TOKENS[name];
      if (desc) {
        return (
          prefix +
          '<span class="mention-group-chip" data-mention-group="' +
          name +
          '" title="@' +
          name +
          " - " +
          desc +
          '">@' +
          name +
          "</span>"
        );
      }
      return prefix + '<span class="mention-highlight">@' + name + "</span>";
    },
  );
  highlightedContent = _highlightBareNames(highlightedContent)
    /* Inline markdown: **bold**, *italic*, `code` */
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
    .replace(/\n/g, "<br>")
    .replace(
      /(#(?:general|todo|research|deploy|telegram|orchestrator))\b/g,
      '<span class="channel-highlight">$1</span>',
    )
    /* Cross-repo references: `owner/repo#N` → GitHub issue link.
     * Must run before the bare `#N` rule so the slash-prefixed form wins
     * (the bare rule has a `(?<![\/\w])` guard that lets this pass). */
    .replace(
      /(^|[^\w\/])([\w.-]+\/[\w.-]+)#(\d+)\b/g,
      function (_m, lead, repo, num) {
        var label = repo + "#" + num;
        return (
          lead +
          '<a class="issue-link" data-issue-repo="' +
          repo +
          '" data-issue-num="' +
          num +
          '" data-issue-label="' +
          label +
          '" href="https://github.com/' +
          repo +
          "/issues/" +
          num +
          '" target="_blank" rel="noopener">' +
          label +
          "</a>"
        );
      },
    )
    .replace(
      /(?<![\/\w])#(\d+)\b/g,
      '<a class="issue-link" data-issue-num="$1" data-issue-label="#$1" href="https://github.com/ywatanabe1989/todo/issues/$1" target="_blank">#$1</a>',
    )
    /* Auto-link plain URLs. The lookbehind only blocks URLs that are
     * already inside an HTML attribute value (`="...` or `'...`); the
     * previous version also blocked `>`, which mis-fired on URLs sitting
     * right after a `<br>` tag (the prior `\n → <br>` substitution leaves
     * `>` as the char immediately before any line-leading URL), so URLs
     * at the start of a wrapped line never became clickable.
     * todo#239 / msg 5961 / ywatanabe report msg 6058. */
    /* Auto-link msg#NNN references — click opens thread panel (msg#9644 spec) */
    .replace(
      /\bmsg#(\d+)\b/g,
      '<a class="msg-ref-link" href="#" data-msg-ref="$1" onclick="event.preventDefault();jumpToMsg(\'$1\')">msg#$1</a>',
    )
    .replace(
      /(?<!["'=])(https?:\/\/[^\s<>"')\]]+)/g,
      '<a class="chat-link" href="$1" target="_blank" rel="noopener">$1</a>',
    )
    /* Auto-link bare www. URLs (no scheme) — prepend https:// for href.
     * Must run after the https?:// replacement so we don't double-link.
     * Skip if already inside an <a> tag (lookbehind for `href="`). */
    .replace(
      /(?<!["'=\/])\b(www\.[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}[^\s<>"')\]]*)/g,
      '<a class="chat-link" href="https://$1" target="_blank" rel="noopener">$1</a>',
    );

  /* Restore fenced code blocks (placeholders → <pre><code>) (#375) */
  if (_codeBlocks.length > 0) {
    highlightedContent = highlightedContent.replace(
      /\x00(\d+)\x00/g,
      function (_, idx) { return _codeBlocks[parseInt(idx, 10)]; }
    );
  }

  /* Fold long posts (>10 lines).
   * Count <br> splits AND lines inside <pre> blocks for an accurate total. */
  var MAX_LINES = 10;
  var _countLines = function (html) {
    var n = html.split("<br>").length;
    /* Each <pre> block contributes (newline count) additional visual lines */
    html.replace(/<pre[\s\S]*?<\/pre>/g, function (pre) {
      n += (pre.match(/\n/g) || []).length;
    });
    return n;
  };
  var lines = highlightedContent.split("<br>");
  var totalLines = _countLines(highlightedContent);
  var isFolded = totalLines > MAX_LINES;
  if (isFolded) {
    var preview = lines.slice(0, MAX_LINES).join("<br>");
    var full = highlightedContent;
    var extraLines = totalLines - MAX_LINES;
    highlightedContent =
      '<div class="msg-preview">' +
      preview +
      "</div>" +
      '<div class="msg-full" style="display:none">' +
      full +
      "</div>" +
      '<button class="msg-fold-btn" tabindex="-1" data-extra="' + extraLines + '">Show more (' +
      extraLines +
      " more lines)</button>";
  }
  /* Inline reply reference — if this message has metadata.reply_to
   * pointing at another message id, render a small quoted preview of
   * the parent above the content so the relationship is visible in
   * the main feed (not only in the thread side panel). */
  var replyRefHtml = "";
  var metaObj = (msg.payload && msg.payload.metadata) || msg.metadata || {};
  var replyToId = metaObj && metaObj.reply_to;
  if (replyToId) {
    var parentEl = document.querySelector(
      '.msg[data-msg-id="' + String(replyToId) + '"]',
    );
    var parentSender = "";
    var parentSnippet = "";
    if (parentEl) {
      var senderEl = parentEl.querySelector(".sender");
      var bodyEl = parentEl.querySelector(".content");
      parentSender = senderEl ? senderEl.textContent : "";
      parentSnippet = bodyEl ? bodyEl.textContent.slice(0, 120) : "";
    }
    replyRefHtml =
      '<div class="msg-reply-ref" data-parent-id="' +
      String(replyToId) +
      '" title="Click to jump to parent">' +
      '<span class="msg-reply-icon">\u21b3</span> ' +
      (parentSender
        ? '<span class="msg-reply-parent">' +
          escapeHtml(parentSender) +
          "</span>: "
        : '<span class="msg-reply-parent">msg#' + replyToId + "</span>: ") +
      '<span class="msg-reply-snippet">' +
      escapeHtml(parentSnippet || "(scroll up to load)") +
      "</span>" +
      "</div>";
  }

  /* attachments already resolved above (for the empty-content guard) */
  var attachmentsHtml = buildAttachmentsHtml(attachments);
  var roleBadge = "";
  var youTag =
    senderName === userName ? ' <span class="you-tag">(You)</span>' : "";
  var senderIcon = getSenderIcon(senderName, isAgent);
  el.innerHTML =
    '<div class="msg-header">' +
    '<span class="msg-icon">' +
    senderIcon +
    "</span>" +
    '<span class="sender" style="color:' +
    senderColor +
    '">' +
    escapeHtml(cleanAgentName(senderName)) +
    "</span>" +
    youTag +
    roleBadge +
    '<a href="#" class="channel channel-link" data-channel="' +
    escapeHtml(channel) +
    '" title="Switch to ' +
    escapeHtml(channel) +
    '">' +
    escapeHtml(channel) +
    "</a>" +
    '<span class="ts" title="' +
    escapeHtml(fullTs) +
    '">' +
    ts +
    "</span>" +
    (msg.id ? '<span class="msg-id-chip" title="Message ID">#' + msg.id + '</span>' : "") +
    (msg.edited
      ? '<span class="msg-edited-tag" title="' +
        escapeHtml(msg.edited_at ? "Edited " + timeAgo(msg.edited_at) : "Edited") +
        '">(edited)</span>'
      : "") +
    "</div>" +
    replyRefHtml +
    '<div class="content">' +
    highlightedContent +
    "</div>" +
    attachmentsHtml +
    (msg.id
      ? '<div class="msg-reactions" data-msg-id="' + msg.id + '"></div>'
      : "") +
    (msg.id
      ? '<button class="msg-react-btn" type="button" title="React" onclick="openReactionPicker(this,' +
        msg.id +
        ')">+</button>'
      : "") +
    (msg.id
      ? '<button class="msg-thread-btn" type="button" title="Reply in thread" onclick="openThreadForMessage(' +
        msg.id +
        ')">\uD83D\uDCAC</button>'
      : "") +
    (msg.id
      ? '<button class="permalink-btn msg-permalink-btn" type="button" tabindex="-1" ' +
        'title="Copy link to this thread" ' +
        'onclick="event.stopPropagation();copyThreadPermalink(' +
        msg.id +
        ',this)">\uD83D\uDD17</button>'
      : "") +
    (msg.id && senderName === userName
      ? '<button class="msg-edit-btn" type="button" title="Edit message" onclick="startEditMessage(' +
        msg.id +
        ')">&#9998;</button>'
      : "") +
    (msg.id && senderName === userName
      ? '<button class="msg-delete-btn" type="button" title="Delete message" onclick="deleteMessage(' +
        msg.id +
        ')">&#10005;</button>'
      : "") +
    (function () {
      var tc = msg.thread_count || 0;
      if (!msg.id || tc === 0) return "";
      return (
        '<div class="msg-thread-count" data-msg-id="' +
        msg.id +
        '" onclick="openThreadForMessage(' +
        msg.id +
        ')">' +
        "\uD83D\uDCAC " +
        tc +
        (tc === 1 ? " reply" : " replies") +
        "</div>"
      );
    })();
  if (currentChannel && channel !== currentChannel) {
    el.style.display = "none";
  }
  var container = document.getElementById("messages");
  /* Only auto-scroll if user is already near the bottom (within 150px).
   * This prevents forced scrolling while the user is typing or reading
   * older messages, which on mobile Safari can disrupt the textarea
   * (dismiss keyboard, lose IME composition, or reset input value). */
  var nearBottom =
    container.scrollHeight - container.scrollTop - container.clientHeight < 150;
  /* Preserve textarea focus/selection across DOM mutation + scroll.
   * todo#225: on the dashboard, inbound WS messages were causing the
   * compose textarea to lose focus mid-typing. The root cause is the
   * appendChild + scrollTop write on #messages: even though the textarea
   * is a sibling, browsers can blur it when the focused element is in a
   * container whose layout shifts under an async scroll write, and the
   * same path is responsible for todo#55's pending-attachment / input
   * state loss. We snapshot focus before the mutation and restore it
   * afterward, and we skip the auto-scroll entirely while the user is
   * actively typing so we don't yank their viewport either.
   *
   * Voice recording: additionally save/restore the full activeElement +
   * selection so that DOM mutations during SpeechRecognition don't steal
   * focus away from the textarea that the speech API is writing into.
   * (Note: appendMessage already returns early when window.isVoiceRecording
   * is true — this path is reached only for non-voice DOM updates.) */
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  /* Also capture any other focused element (e.g. thread textarea) */
  var savedActiveEl = document.activeElement;
  var savedActiveStart = 0;
  var savedActiveEnd = 0;
  if (savedActiveEl && savedActiveEl !== msgInput &&
      (savedActiveEl.tagName === "TEXTAREA" || savedActiveEl.tagName === "INPUT")) {
    try {
      savedActiveStart = savedActiveEl.selectionStart;
      savedActiveEnd = savedActiveEl.selectionEnd;
    } catch (_) {}
  }
  container.appendChild(el);
  /* Render any mermaid diagrams inside the newly appended message */
  _renderMermaidIn(el);
  /* todo#274 Part 2: re-apply multi-select feed filter so newly-arrived
   * messages get hidden if they don't match the current selection. */
  if (typeof applyFeedFilter === "function") {
    try { applyFeedFilter(); } catch (_) {}
  }
  /* Auto-scroll: skip entirely during voice recording to prevent the
   * scrollTop write from interfering with the SpeechRecognition session.
   * Outside of voice recording, always scroll when near the bottom. */
  if (nearBottom && !window.isVoiceRecording) {
    container.scrollTop = container.scrollHeight;
  }
  /* Restore focus + selection for the main compose textarea */
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
  }
  /* Restore focus + selection for any other text input (e.g. thread textarea) */
  if (savedActiveEl && savedActiveEl !== msgInput &&
      document.activeElement !== savedActiveEl &&
      (savedActiveEl.tagName === "TEXTAREA" || savedActiveEl.tagName === "INPUT")) {
    try {
      savedActiveEl.focus();
      savedActiveEl.setSelectionRange(savedActiveStart, savedActiveEnd);
    } catch (_) {}
  }
  applyIssueTitleHints(el);
}

function filterMessages() {
  /* todo#274 Part 2: delegate to applyFeedFilter which supports
   * AND across multiple selected sidebar items. */
  applyFeedFilter();
}

function applyFeedFilter() {
  var selectedChannels = [];
  var selectedAgents = [];
  document
    .querySelectorAll(".sidebar .channel-item.selected[data-channel]")
    .forEach(function (el) {
      selectedChannels.push(el.getAttribute("data-channel"));
    });
  document
    .querySelectorAll(".sidebar .agent-card.selected[data-agent-name]")
    .forEach(function (el) {
      selectedAgents.push(el.getAttribute("data-agent-name"));
    });
  var hasAnySelection =
    selectedChannels.length > 0 || selectedAgents.length > 0;
  var msgs = document.querySelectorAll(".msg");
  msgs.forEach(function (el) {
    if (!hasAnySelection) {
      if (!currentChannel) {
        el.style.display = "";
      } else {
        var ch0 = el.getAttribute("data-channel");
        el.style.display = ch0 === currentChannel ? "" : "none";
      }
      return;
    }
    var ch = el.getAttribute("data-channel");
    var sender = el.getAttribute("data-sender");
    var chOk =
      selectedChannels.length === 0 || selectedChannels.indexOf(ch) !== -1;
    var agOk =
      selectedAgents.length === 0 || selectedAgents.indexOf(sender) !== -1;
    el.style.display = chOk && agOk ? "" : "none";
  });
}

async function loadHistory() {
  /* If a channel is currently selected, delegate to loadChannelHistory so we
   * only fetch that channel's messages.  This prevents a race/flash where the
   * full all-channels response could briefly render before the client-side
   * filter hides non-matching messages (todo#247). */
  if (currentChannel) {
    return loadChannelHistory(currentChannel);
  }
  try {
    var res = await fetch(apiUrl("/api/messages/?limit=100"), {
      credentials: "same-origin",
    });
    if (!res.ok) {
      console.error("loadHistory: API returned", res.status, res.statusText);
      return;
    }
    var messages = await res.json();
    /* API returns newest-first (-ts); reverse for chronological display */
    messages.reverse();
    var container = document.getElementById("messages");

    /* Preserve the textarea value and pending attachments across history
     * rebuilds.  On mobile Safari, large DOM mutations (innerHTML="")
     * while the keyboard is up can cause the browser to reset or blur
     * the focused textarea, losing the user's in-progress message. */
    var msgInput = document.getElementById("msg-input");
    var savedValue = msgInput ? msgInput.value : "";
    var hadFocus = msgInput && document.activeElement === msgInput;
    var savedStart = msgInput ? msgInput.selectionStart : 0;
    var savedEnd = msgInput ? msgInput.selectionEnd : 0;
    /* Save pending attachments (uploaded files waiting to be sent) */
    var savedAttachments = (typeof pendingAttachments !== "undefined") ? pendingAttachments.slice() : [];

    container.innerHTML = "";
    knownMessageKeys = {};
    messages.forEach(function (row) {
      var key = messageKey(row.sender, row.ts, row.content);
      knownMessageKeys[key] = true;
      appendMessage({
        id: row.id,
        type: "message",
        sender: row.sender,
        sender_type: row.sender_type,
        ts: row.ts,
        edited: row.edited || false,
        edited_at: row.edited_at || null,
        thread_count: row.thread_count || 0,
        metadata: row.metadata || {},
        payload: {
          channel: row.channel,
          content: row.content,
          attachments:
            (row.metadata && row.metadata.attachments) || row.attachments || [],
        },
      });
    });
    container.scrollTop = container.scrollHeight;

    /* Restore textarea state if the DOM rebuild clobbered it */
    if (msgInput && savedValue && !msgInput.value) {
      msgInput.value = savedValue;
      if (hadFocus) {
        msgInput.focus();
        try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
      }
    }
    /* Restore pending attachments if they were lost */
    if (savedAttachments.length && typeof pendingAttachments !== "undefined" && !pendingAttachments.length) {
      pendingAttachments = savedAttachments;
      if (typeof _renderAttachmentTray === "function") _renderAttachmentTray();
    }

    historyLoaded = true;
    /* If the page was loaded with ?thread=<id>, auto-open that thread now
     * that the parent message DOM exists (todo#237). */
    if (typeof applyThreadUrlOnLoad === "function") {
      try { applyThreadUrlOnLoad(); } catch (_) {}
    }
    /* Fetch reactions for all loaded messages */
    if (typeof fetchReactionsForMessages === "function") {
      var ids = messages
        .map(function (r) {
          return r.id;
        })
        .filter(Boolean);
      fetchReactionsForMessages(ids);
    }
  } catch (e) {
    console.error("loadHistory failed:", e);
  }
}

/* Lightweight alternative to loadHistory for WebSocket reconnects.
 * Fetches recent messages and appends only those we haven't seen,
 * avoiding the full innerHTML="" rebuild that disrupts the textarea
 * on mobile Safari. */
async function fetchNewMessages() {
  try {
    var endpoint = currentChannel
      ? "/api/history/" + encodeURIComponent(currentChannel) + "?limit=50"
      : "/api/messages/?limit=50";
    var res = await fetch(apiUrl(endpoint), { credentials: "same-origin" });
    if (!res.ok) return;
    var messages = await res.json();
    messages.reverse();
    messages.forEach(function (row) {
      var key = messageKey(row.sender, row.ts, row.content);
      if (knownMessageKeys[key]) return;
      knownMessageKeys[key] = true;
      appendMessage({
        id: row.id,
        type: "message",
        sender: row.sender,
        sender_type: row.sender_type,
        ts: row.ts,
        edited: row.edited || false,
        edited_at: row.edited_at || null,
        thread_count: row.thread_count || 0,
        metadata: row.metadata || {},
        payload: {
          channel: row.channel || currentChannel || "",
          content: row.content,
          attachments:
            (row.metadata && row.metadata.attachments) || row.attachments || [],
        },
      });
    });
  } catch (e) {
    console.warn("fetchNewMessages failed:", e);
  }
}

async function loadChannelHistory(channel) {
  try {
    var encodedChannel = encodeURIComponent(channel);
    var res = await fetch(
      apiUrl("/api/history/" + encodedChannel + "?limit=100"),
      { credentials: "same-origin" },
    );
    if (!res.ok) {
      console.error(
        "loadChannelHistory: API returned",
        res.status,
        res.statusText,
      );
      return;
    }
    var messages = await res.json();
    /* API returns newest-first (-ts); reverse for chronological display */
    messages.reverse();
    var container = document.getElementById("messages");

    /* Preserve textarea value + attachments -- see loadHistory */
    var msgInput = document.getElementById("msg-input");
    var savedValue = msgInput ? msgInput.value : "";
    var hadFocus = msgInput && document.activeElement === msgInput;
    var savedStart = msgInput ? msgInput.selectionStart : 0;
    var savedEnd = msgInput ? msgInput.selectionEnd : 0;
    var savedAttachments = (typeof pendingAttachments !== "undefined") ? pendingAttachments.slice() : [];

    container.innerHTML = "";
    knownMessageKeys = {};
    messages.forEach(function (row) {
      var key = messageKey(row.sender, row.ts, row.content);
      knownMessageKeys[key] = true;
      appendMessage({
        id: row.id,
        type: "message",
        sender: row.sender,
        sender_type: row.sender_type,
        ts: row.ts,
        edited: row.edited || false,
        edited_at: row.edited_at || null,
        thread_count: row.thread_count || 0,
        metadata: row.metadata || {},
        payload: {
          channel: channel,
          content: row.content,
          attachments:
            (row.metadata && row.metadata.attachments) || row.attachments || [],
        },
      });
    });
    container.scrollTop = container.scrollHeight;

    /* Restore textarea state if the DOM rebuild clobbered it */
    if (msgInput && savedValue && !msgInput.value) {
      msgInput.value = savedValue;
      if (hadFocus) {
        msgInput.focus();
        try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
      }
    }
    /* Restore pending attachments */
    if (savedAttachments.length && typeof pendingAttachments !== "undefined" && !pendingAttachments.length) {
      pendingAttachments = savedAttachments;
      if (typeof _renderAttachmentTray === "function") _renderAttachmentTray();
    }

    historyLoaded = true;
    /* If the page was loaded with ?thread=<id>, auto-open that thread now */
    if (typeof applyThreadUrlOnLoad === "function") {
      try { applyThreadUrlOnLoad(); } catch (_) {}
    }
    if (typeof fetchReactionsForMessages === "function") {
      var ids = messages
        .map(function (r) {
          return r.id;
        })
        .filter(Boolean);
      fetchReactionsForMessages(ids);
    }
  } catch (e) {
    console.error("Failed to load channel history:", e);
  }
}

function updateChannelSelect() {
  /* Channel select removed -- using sidebar selection instead */
}

function sendMessage() {
  var input = document.getElementById("msg-input");
  /* In multi-select mode currentChannel is null; fall back to lastActiveChannel
   * so the message goes to the last focused channel (#9694). */
  var channel = currentChannel || (typeof lastActiveChannel !== "undefined" && lastActiveChannel) || "#general";
  var text = input.value.trim();

  /* Pull any attachments the user staged via paste/drop/picker before
   * hitting Send. Attachments alone (empty text) are a valid message. */
  var attachments =
    typeof getPendingAttachments === "function" ? getPendingAttachments() : [];
  if (!text && attachments.length === 0) return;

  var payload = { channel: channel, content: text };
  if (attachments.length > 0) payload.attachments = attachments;

  /* Prefer WebSocket send when connected (instant echo), fall back to REST */
  if (wsConnected && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "message", payload: payload }));
  } else {
    sendOrochiMessage({
      type: "message",
      sender: userName,
      payload: payload,
    });
  }
  input.value = "";
  input.style.height = "auto";
  /* Force scroll to bottom immediately on send (#227) */
  var msgContainer = document.getElementById("messages");
  if (msgContainer) {
    msgContainer.scrollTop = msgContainer.scrollHeight;
  }
  if (typeof clearPendingAttachments === "function") {
    clearPendingAttachments();
  }
  /* Clear the per-channel draft now that the message has been sent. */
  try {
    sessionStorage.removeItem(
      "orochi-draft-" + (currentChannel || "__default__")
    );
  } catch (_) {}
  /* Hands-free voice dictation: if the mic is currently listening, the
   * next recognition.result event would re-render the entire cumulative
   * session transcript on top of the now-empty input. Tell voice-input.js
   * to reset its baseText snapshot AND restart the recognition session
   * so the input stays clean. ywatanabe wants to leave the mic on for
   * continuous dictation across multiple sends (msg#6500 / msg#6504). */
  if (typeof window.voiceInputResetAfterSend === "function") {
    try { window.voiceInputResetAfterSend(); } catch (_) {}
  }
}

/* Auto-resize textarea as content grows + persist draft per channel.
 *
 * The draft is keyed by `currentChannel` so switching channels preserves
 * each channel's in-progress message. On page reload (or DOM re-render
 * accident), restoreDraftForCurrentChannel() puts the text back. We use
 * sessionStorage so drafts disappear when the tab closes — closer to a
 * "scratchpad" semantic than localStorage's "permanent" feel.
 */
function _draftKey() {
  try {
    return "orochi-draft-" + (currentChannel || "__default__");
  } catch (_) {
    return "orochi-draft-__default__";
  }
}
function _saveDraft(value) {
  try {
    if (value && value.length > 0) {
      sessionStorage.setItem(_draftKey(), value);
    } else {
      sessionStorage.removeItem(_draftKey());
    }
  } catch (_) { /* sessionStorage may be unavailable in private mode */ }
}
function restoreDraftForCurrentChannel() {
  try {
    var input = document.getElementById("msg-input");
    if (!input) return;
    var saved = sessionStorage.getItem(_draftKey());
    if (saved && !input.value) {
      input.value = saved;
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 200) + "px";
    }
  } catch (_) {}
}
window.restoreDraftForCurrentChannel = restoreDraftForCurrentChannel;
document.getElementById("msg-input").addEventListener("input", function () {
  this.style.height = "auto";
  this.style.height = Math.min(this.scrollHeight, 200) + "px";
  _saveDraft(this.value);
});
restoreDraftForCurrentChannel();

/* Diagnostic blur logger for todo#225 — captures every blur event on
 * #msg-input with timestamp, relatedTarget, and a trimmed stack trace,
 * stored in sessionStorage so a user (or mamba-verifier-mba via
 * playwright) can inspect the last N events with
 *   JSON.parse(sessionStorage.getItem("orochi-blurlog") || "[]")
 * after reproducing the bug. Async-safe (uses requestAnimationFrame to
 * also catch deferred re-blurs that happen after a synchronous
 * focus-restore). Capacity-bounded at 50 entries so it never grows
 * unbounded. Strictly diagnostic — no UI side-effect. */
(function () {
  var input = document.getElementById("msg-input");
  if (!input) return;
  function _logBlur(label, e) {
    try {
      var arr = JSON.parse(sessionStorage.getItem("orochi-blurlog") || "[]");
      var rt = e && e.relatedTarget;
      arr.push({
        t: new Date().toISOString(),
        label: label,
        relatedTarget: rt
          ? (rt.tagName || "?") + "#" + (rt.id || "") + "." + (rt.className || "")
          : null,
        activeAfter: document.activeElement
          ? document.activeElement.tagName + "#" + (document.activeElement.id || "")
          : null,
        stack: (new Error()).stack
          ? (new Error()).stack.split("\n").slice(2, 8).join(" | ")
          : null,
      });
      while (arr.length > 50) arr.shift();
      sessionStorage.setItem("orochi-blurlog", JSON.stringify(arr));
    } catch (_) {}
  }
  input.addEventListener("blur", function (e) {
    _logBlur("sync-blur", e);
    /* Also check after one frame in case something defers focus theft */
    requestAnimationFrame(function () {
      if (document.activeElement !== input) {
        _logBlur("post-rAF-still-blurred", e);
      }
    });
  });
  /* Also expose a one-shot getter for convenience */
  window.getBlurLog = function () {
    try {
      return JSON.parse(sessionStorage.getItem("orochi-blurlog") || "[]");
    } catch (_) { return []; }
  };
})();

/* Systemic focus-theft guard (todo#225 follow-up after blur log analysis at
 * msg#6341): clicking any button or link inside the message feed or thread
 * panel was shifting browser focus away from #msg-input, breaking ywatanabe's
 * mid-typing flow. The previous fix only patched .msg-fold-btn; the blur log
 * exposed five more offenders (.msg-thread-btn, .chat-link, .issue-link,
 * .permalink-btn, .thread-permalink-btn). Rather than chase each one with
 * tabindex / inline onmousedown, we install a single capture-phase mousedown
 * delegate: when #msg-input currently holds focus AND the click target is a
 * <button> or <a> inside .msg / .thread-panel / #messages, preventDefault on
 * mousedown blocks the browser's default focus shift. The click event still
 * fires, so the underlying action (open thread, open URL in new tab, fold,
 * permalink copy, …) runs normally. Form controls (textarea/input/select)
 * are excluded so the user can still tab into #thread-input intentionally. */
document.addEventListener("mousedown", function (e) {
  var msgInput = document.getElementById("msg-input");
  if (!msgInput || document.activeElement !== msgInput) return;
  var t = e.target;
  if (!t || !t.closest) return;
  /* Allow focus shift onto another form control (e.g. thread reply input). */
  var formCtrl = t.closest("textarea, input, select");
  if (formCtrl && formCtrl !== msgInput) return;
  /* Only intercept clicks inside the message feed or thread panel. */
  if (!t.closest("#messages, .msg, .thread-panel")) return;
  /* Block focus shift only for UI controls inside the feed.
   * Exempt: tabindex="-1" elements, and content links (.chat-link,
   * .msg-ref-link, .issue-link) — preventDefault on those suppresses
   * navigation/copy on iOS Safari (todo#381 / #neurovista link regression). */
  var ctrl = t.closest("button, a");
  if (ctrl &&
      ctrl.getAttribute("tabindex") !== "-1" &&
      !ctrl.classList.contains("chat-link") &&
      !ctrl.classList.contains("msg-ref-link") &&
      !ctrl.classList.contains("issue-link")) {
    e.preventDefault();
  }
}, true);

/* Show more / Show less toggle for long messages.
 * Uses delegated click on document to handle dynamically inserted buttons.
 * Replaces the previous fragile inline onclick with arguments.callee. */
document.addEventListener("click", function (e) {
  var btn = e.target.closest(".msg-fold-btn");
  if (!btn) return;
  e.preventDefault();
  var parent = btn.parentElement;
  if (!parent) return;
  var previewEl = parent.querySelector(".msg-preview");
  var fullEl = parent.querySelector(".msg-full");
  if (!previewEl || !fullEl) return;
  var extra = btn.getAttribute("data-extra") || "?";
  if (fullEl.style.display === "none") {
    fullEl.style.display = "block";
    previewEl.style.display = "none";
    btn.textContent = "Show less";
    /* Render mermaid diagrams that became visible in the expanded section */
    _renderMermaidIn(fullEl);
  } else {
    fullEl.style.display = "none";
    previewEl.style.display = "block";
    btn.textContent = "Show more (" + extra + " more lines)";
  }
});

/* Mermaid raw-script toggle — delegated click handler */
document.addEventListener("click", function (e) {
  var btn = e.target.closest(".mermaid-toggle");
  if (!btn) return;
  e.preventDefault();
  var container = btn.closest(".mermaid-container");
  if (!container) return;
  var rawEl = container.querySelector(".mermaid-raw");
  if (!rawEl) return;
  var isHidden = rawEl.style.display === "none" || rawEl.style.display === "";
  rawEl.style.display = isHidden ? "block" : "none";
  btn.textContent = isHidden ? "Hide raw" : "Show raw";
});

/* Defensive blur watchdog (todo#225 second-order regression).
 * msg#6692: ywatanabe says focus drops *after an idle period when a
 * delayed post arrives* — i.e. NOT a click event, so the mousedown
 * delegate above can't catch it. Some async setInterval / WS-driven
 * DOM mutation is firing focus() on something else, or the textarea
 * itself is being briefly unmounted by a re-render. Rather than chase
 * every async path, install a one-shot watchdog: if #msg-input loses
 * focus AND nothing else useful (form control / link the user clicked
 * intentionally) took focus within the next paint frame, snap focus
 * straight back. The selection range is restored too so the cursor
 * lands where the user left it. We only re-focus when the textarea
 * still has user-typed content AND the focus shifted to <body> /
 * <button> / <a> — the "implicit blur" pattern — so we never fight
 * an intentional click into another textarea / input / select. */
(function () {
  var msgInput = document.getElementById("msg-input");
  if (!msgInput) return;
  msgInput.addEventListener("blur", function (e) {
    if (window.__voiceInputAllowBlur) return;
    var savedStart = msgInput.selectionStart || 0;
    var savedEnd = msgInput.selectionEnd || 0;
    var rt = e && e.relatedTarget;
    /* If the user clicked into another form control on purpose, leave
     * the focus where they put it. */
    if (rt && rt.tagName) {
      var tn = rt.tagName.toUpperCase();
      if (tn === "TEXTAREA" || tn === "INPUT" || tn === "SELECT") return;
      if (rt.isContentEditable) return;
    }
    requestAnimationFrame(function () {
      var still = document.activeElement;
      if (still === msgInput) return;
      /* Don't fight a real focus into another control. */
      if (still && still.tagName) {
        var stn = still.tagName.toUpperCase();
        if (stn === "TEXTAREA" || stn === "INPUT" || stn === "SELECT") return;
        if (still.isContentEditable) return;
      }
      /* todo#315: don't snap focus back if the user is actively
       * selecting text inside the message feed — refocusing would
       * collapse the selection and make copy impossible. */
      try {
        var sel = window.getSelection && window.getSelection();
        if (sel && sel.toString().length > 0) {
          var anchor = sel.anchorNode;
          if (anchor && anchor.nodeType === 3) anchor = anchor.parentElement;
          if (anchor && anchor.closest &&
              anchor.closest("#messages, .msg, .thread-panel")) {
            return;
          }
        }
      } catch (_) {}
      try {
        msgInput.focus();
        msgInput.setSelectionRange(savedStart, savedEnd);
      } catch (_) {}
    });
  });
})();

document.getElementById("msg-send").addEventListener("click", function (e) {
  e.preventDefault();
  /* On mobile Safari, tapping the send button blurs the textarea before
   * the click handler fires, which can dismiss the keyboard and cause
   * unexpected scrolling. We call sendMessage synchronously here. */
  sendMessage();
  /* Re-focus the textarea so the keyboard stays open on mobile */
  document.getElementById("msg-input").focus();
});
document.getElementById("msg-input").addEventListener("keydown", function (e) {
  /* Ctrl+U / Cmd+U → trigger file upload picker (msg#9877) */
  var isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
  if ((isMac ? e.metaKey : e.ctrlKey) && e.key === "u") {
    e.preventDefault();
    var fi = document.getElementById("file-input");
    if (fi) fi.click();
    return;
  }
  if (e.key === "Enter") {
    var dd = document.getElementById("mention-dropdown");
    if (dd && dd.classList.contains("visible")) return;
    /* todo#332 v2: Alt+Enter is reserved for voice toggle (see voice-input.js).
     * Shift+Enter remains the newline shortcut. Plain Enter sends. */
    if (e.shiftKey) return;
    if (e.altKey) {
      /* Voice toggle handled by voice-input.js global handler — just prevent default */
      e.preventDefault();
      return;
    }
    e.preventDefault();
    sendMessage();
  }
});

/* --- Edit / Delete message support --- */

function startEditMessage(msgId) {
  var el = document.querySelector('.msg[data-msg-id="' + msgId + '"]');
  if (!el) return;
  var contentEl = el.querySelector(".content");
  if (!contentEl) return;
  /* Prevent double-editing */
  if (el.querySelector(".msg-edit-input")) return;

  /* Extract plain text from rendered HTML (reverse of escapeHtml + <br>) */
  var currentText = contentEl.innerText || contentEl.textContent || "";

  /* Hide content and action buttons while editing */
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  contentEl.style.display = "none";
  var editContainer = document.createElement("div");
  editContainer.className = "msg-edit-container";
  editContainer.innerHTML =
    '<textarea class="msg-edit-input" rows="2">' +
    escapeHtml(currentText) +
    "</textarea>" +
    '<div class="msg-edit-actions">' +
    '<button class="msg-edit-save" type="button">Save</button>' +
    '<button class="msg-edit-cancel" type="button">Cancel</button>' +
    "</div>";
  contentEl.parentNode.insertBefore(editContainer, contentEl.nextSibling);
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
  }

  var textarea = editContainer.querySelector(".msg-edit-input");
  textarea.focus();
  textarea.setSelectionRange(textarea.value.length, textarea.value.length);

  /* Auto-resize */
  textarea.style.height = "auto";
  textarea.style.height = Math.min(textarea.scrollHeight, 200) + "px";

  editContainer
    .querySelector(".msg-edit-save")
    .addEventListener("click", function () {
      saveEditMessage(msgId, textarea.value);
    });
  editContainer
    .querySelector(".msg-edit-cancel")
    .addEventListener("click", function () {
      cancelEditMessage(msgId);
    });
  textarea.addEventListener("keydown", function (e) {
    /* todo#332: Shift+Enter and Alt+Enter both insert a newline */
    if (e.key === "Enter" && !e.shiftKey && !e.altKey) {
      e.preventDefault();
      saveEditMessage(msgId, textarea.value);
    }
    if (e.key === "Escape") {
      cancelEditMessage(msgId);
    }
  });
}

function saveEditMessage(msgId, newText) {
  newText = (newText || "").trim();
  if (!newText) return;
  fetch(apiUrl("/api/messages/" + msgId + "/"), {
    method: "PATCH",
    headers: orochiHeaders(),
    credentials: "same-origin",
    body: JSON.stringify({ text: newText }),
  })
    .then(function (res) {
      if (!res.ok) {
        res.json().then(function (d) {
          console.error("Edit failed:", d.error || res.status);
        });
      }
      /* The WebSocket broadcast will update the UI */
    })
    .catch(function (e) {
      console.error("Edit error:", e);
    });
  /* Immediately close the editor for snappy UX */
  cancelEditMessage(msgId);
}

function cancelEditMessage(msgId) {
  var el = document.querySelector('.msg[data-msg-id="' + msgId + '"]');
  if (!el) return;
  var editContainer = el.querySelector(".msg-edit-container");
  if (editContainer) editContainer.remove();
  var contentEl = el.querySelector(".content");
  if (contentEl) contentEl.style.display = "";
}

function deleteMessage(msgId) {
  fetch(apiUrl("/api/messages/" + msgId + "/"), {
    method: "DELETE",
    headers: orochiHeaders(),
    credentials: "same-origin",
  })
    .then(function (res) {
      if (!res.ok) {
        res.json().then(function (d) {
          console.error("Delete failed:", d.error || res.status);
        });
      }
      /* The WebSocket broadcast will remove it from the UI */
    })
    .catch(function (e) {
      console.error("Delete error:", e);
    });
}

function handleMessageEdit(event) {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var el = document.querySelector(
    '.msg[data-msg-id="' + event.message_id + '"]',
  );
  if (!el) return;
  var contentEl = el.querySelector(".content");
  if (contentEl) {
    contentEl.innerHTML = escapeHtml(event.text).replace(/\n/g, "<br>");
  }
  /* Add or update the (edited) tag */
  var header = el.querySelector(".msg-header");
  if (header && !header.querySelector(".msg-edited-tag")) {
    var tag = document.createElement("span");
    tag.className = "msg-edited-tag";
    tag.title = event.edited_at
      ? "Edited " + timeAgo(event.edited_at)
      : "Edited";
    tag.textContent = "(edited)";
    header.appendChild(tag);
  }
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
  }
}

function handleMessageDelete(event) {
  var el = document.querySelector(
    '.msg[data-msg-id="' + event.message_id + '"]',
  );
  if (el) {
    el.classList.add("msg-deleted");
    setTimeout(function () {
      el.remove();
    }, 300);
  }
}

/* Timestamps are now absolute (YYYY-MM-DD HH:mm:ss), no periodic refresh needed */

/* --- Long-press context menu (mobile) ---
 * On touch devices, holding a finger on a message for ~500ms opens a
 * floating action menu with Reply / React / Edit / Delete / Copy.
 * Desktop continues to use the existing hover buttons.
 *
 * Implementation notes:
 *   - Uses event delegation on #messages so it picks up dynamically
 *     appended .msg elements without per-message wiring.
 *   - Cancels if the finger moves >10px (treat as scroll) or lifts early.
 *   - Suppresses the synthetic click that follows touchend so taps on
 *     links/buttons inside the message don't fire after a long press.
 *   - Skips when the touch target is an interactive control (textarea,
 *     button, input, link, image attachment).
 */
(function () {
  var LONG_PRESS_MS = 500;
  var MOVE_TOLERANCE = 10;
  var pressTimer = null;
  var pressTarget = null;
  var startX = 0;
  var startY = 0;
  var didLongPress = false;
  var openMenu = null;

  function isTouchDevice() {
    return (
      "ontouchstart" in window ||
      (navigator.maxTouchPoints && navigator.maxTouchPoints > 0)
    );
  }

  function isInteractiveTarget(node) {
    while (node && node !== document.body) {
      var tag = node.tagName;
      if (
        tag === "TEXTAREA" ||
        tag === "BUTTON" ||
        tag === "INPUT" ||
        tag === "A" ||
        tag === "SELECT"
      ) {
        return true;
      }
      if (node.classList && node.classList.contains("msg-edit-container")) {
        return true;
      }
      node = node.parentNode;
    }
    return false;
  }

  function closeLongPressMenu() {
    if (openMenu && openMenu.parentNode) {
      openMenu.parentNode.removeChild(openMenu);
    }
    openMenu = null;
    document.removeEventListener("touchstart", _outsideHandler, true);
    document.removeEventListener("mousedown", _outsideHandler, true);
  }

  function _outsideHandler(e) {
    if (openMenu && !openMenu.contains(e.target)) {
      closeLongPressMenu();
    }
  }

  function getMessageMeta(msgEl) {
    var idStr = msgEl.getAttribute("data-msg-id");
    var msgId = idStr ? parseInt(idStr, 10) : null;
    var senderEl = msgEl.querySelector(".sender");
    var sender = senderEl ? senderEl.textContent.trim() : "";
    var contentEl = msgEl.querySelector(".content");
    var text = contentEl ? contentEl.innerText || contentEl.textContent || "" : "";
    var isOwn =
      typeof userName !== "undefined" &&
      sender &&
      (sender === userName || sender === cleanAgentName(userName));
    return { msgId: msgId, sender: sender, text: text, isOwn: isOwn };
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).catch(function () {});
      return;
    }
    /* Fallback for older mobile Safari */
    try {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    } catch (_) {}
  }

  function showLongPressMenu(msgEl, x, y) {
    closeLongPressMenu();
    var meta = getMessageMeta(msgEl);
    if (!meta.msgId) return;

    var menu = document.createElement("div");
    menu.className = "long-press-menu";

    var actions = [
      {
        label: "Reply",
        icon: "\uD83D\uDCAC",
        run: function () {
          if (typeof openThreadForMessage === "function") {
            openThreadForMessage(meta.msgId);
          }
        },
      },
      {
        label: "React",
        icon: "\u263A",
        run: function () {
          var btn = msgEl.querySelector(".msg-react-btn");
          if (typeof openReactionPicker === "function") {
            openReactionPicker(btn || msgEl, meta.msgId);
          }
        },
      },
    ];
    if (meta.isOwn) {
      actions.push({
        label: "Edit",
        icon: "\u270F\uFE0F",
        run: function () {
          if (typeof startEditMessage === "function") {
            startEditMessage(meta.msgId);
          }
        },
      });
      actions.push({
        label: "Delete",
        icon: "\uD83D\uDDD1\uFE0F",
        cls: "danger",
        run: function () {
          if (typeof deleteMessage === "function") {
            deleteMessage(meta.msgId);
          }
        },
      });
    }
    actions.push({
      label: "Copy text",
      icon: "\uD83D\uDCCB",
      run: function () {
        copyText(meta.text);
      },
    });

    actions.forEach(function (a) {
      var item = document.createElement("button");
      item.type = "button";
      item.className = "long-press-item" + (a.cls ? " " + a.cls : "");
      item.innerHTML =
        '<span class="long-press-icon">' +
        a.icon +
        '</span><span class="long-press-label">' +
        a.label +
        "</span>";
      item.addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        closeLongPressMenu();
        try {
          a.run();
        } catch (err) {
          console.error("long-press action failed:", err);
        }
      });
      menu.appendChild(item);
    });

    /* Position: anchor near touch point but clamp to viewport */
    document.body.appendChild(menu);
    var rect = menu.getBoundingClientRect();
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var left = Math.min(Math.max(8, x - rect.width / 2), vw - rect.width - 8);
    var top = y + 12;
    if (top + rect.height > vh - 8) {
      top = Math.max(8, y - rect.height - 12);
    }
    menu.style.left = left + "px";
    menu.style.top = top + "px";

    openMenu = menu;
    /* Defer outside-click binding so the originating touch doesn't close it */
    setTimeout(function () {
      document.addEventListener("touchstart", _outsideHandler, true);
      document.addEventListener("mousedown", _outsideHandler, true);
    }, 0);

    /* Haptic hint where supported */
    if (navigator.vibrate) {
      try { navigator.vibrate(15); } catch (_) {}
    }
  }

  function clearPressTimer() {
    if (pressTimer) {
      clearTimeout(pressTimer);
      pressTimer = null;
    }
    pressTarget = null;
  }

  function onTouchStart(e) {
    if (e.touches.length !== 1) return;
    var t = e.target;
    if (isInteractiveTarget(t)) return;
    var msgEl = t.closest && t.closest(".msg");
    if (!msgEl || msgEl.classList.contains("msg-system")) return;
    if (!msgEl.getAttribute("data-msg-id")) return;

    didLongPress = false;
    pressTarget = msgEl;
    var touch = e.touches[0];
    startX = touch.clientX;
    startY = touch.clientY;

    pressTimer = setTimeout(function () {
      didLongPress = true;
      showLongPressMenu(msgEl, startX, startY);
    }, LONG_PRESS_MS);
  }

  function onTouchMove(e) {
    if (!pressTimer) return;
    var touch = e.touches[0];
    if (!touch) return;
    var dx = Math.abs(touch.clientX - startX);
    var dy = Math.abs(touch.clientY - startY);
    if (dx > MOVE_TOLERANCE || dy > MOVE_TOLERANCE) {
      clearPressTimer();
    }
  }

  function onTouchEnd() {
    clearPressTimer();
  }

  function onTouchCancel() {
    clearPressTimer();
  }

  /* Suppress the synthetic click that follows a long-press touch sequence
   * so the underlying message links/buttons don't fire after the menu opens. */
  function onClickCapture(e) {
    if (didLongPress) {
      didLongPress = false;
      e.preventDefault();
      e.stopPropagation();
    }
  }

  function init() {
    if (!isTouchDevice()) return;
    var container = document.getElementById("messages");
    if (!container) return;
    container.addEventListener("touchstart", onTouchStart, { passive: true });
    container.addEventListener("touchmove", onTouchMove, { passive: true });
    container.addEventListener("touchend", onTouchEnd, { passive: true });
    container.addEventListener("touchcancel", onTouchCancel, { passive: true });
    container.addEventListener("click", onClickCapture, true);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

/* Channel name click → switch channel (#211) */
document.addEventListener("click", function (e) {
  var link = e.target.closest(".channel-link");
  if (!link) return;
  e.preventDefault();
  var ch = link.getAttribute("data-channel");
  if (!ch) return;
  if (typeof currentChannel !== "undefined") {
    if (currentChannel === ch) {
      if (typeof setCurrentChannel === "function") setCurrentChannel(null);
      else currentChannel = null;
      if (typeof loadHistory === "function") loadHistory();
    } else {
      if (typeof setCurrentChannel === "function") setCurrentChannel(ch);
      else currentChannel = ch;
      if (typeof loadChannelHistory === "function") loadChannelHistory(ch);
    }
    if (typeof addTag === "function") addTag("channel", ch);
    if (typeof fetchStats === "function") fetchStats();
  }
});
