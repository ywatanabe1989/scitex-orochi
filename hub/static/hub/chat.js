/* Chat module -- message display, history, filtering */
/* globals: escapeHtml, getAgentColor, timeAgo, cachedAgentNames, userName,
   currentChannel, knownMessageKeys, messageKey, sendOrochiMessage,
   updateResourcePanel, token, apiUrl */

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
  var label = a.getAttribute("data-issue-label") || a.textContent;
  a.title = label + " " + title;
  a.innerHTML =
    escapeHtml(label) +
    ' <span class="issue-link-title">(' +
    escapeHtml(title) +
    ")</span>";
  a.dataset.hinted = "1";
}

function _fetchCrossRepoTitle(repo, num, cb) {
  var key = repo + "#" + num;
  if (issueTitleCache[key] !== undefined) {
    cb(issueTitleCache[key] || null);
    return;
  }
  if (issueTitleInflight[key]) return;
  issueTitleInflight[key] = true;
  var url =
    apiUrl("/api/github/issue-title") +
    "?repo=" +
    encodeURIComponent(repo) +
    "&number=" +
    encodeURIComponent(num);
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

function appendMessage(msg) {
  var el = document.createElement("div");
  var senderName = msg.sender || "unknown";
  var isAgent = msg.sender_type === "agent" || isKnownAgent(senderName);
  el.className = "msg" + (isAgent ? "" : " msg-human");
  if (msg.id) el.setAttribute("data-msg-id", String(msg.id));
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

  var highlightedContent = escaped.replace(
    /(^|[\s\r\n])@([\w@.\-]+)/g,
    function (_match, prefix, name) {
      return prefix + '<span class="mention-highlight">@' + name + "</span>";
    },
  );
  highlightedContent = _highlightBareNames(highlightedContent)
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
    .replace(
      /(?<![="'>])(https?:\/\/[^\s<>"')\]]+)/g,
      '<a class="chat-link" href="$1" target="_blank" rel="noopener">$1</a>',
    );
  /* Fold long posts (>10 lines) */
  var MAX_LINES = 10;
  var lines = highlightedContent.split("<br>");
  var isFolded = lines.length > MAX_LINES;
  if (isFolded) {
    var preview = lines.slice(0, MAX_LINES).join("<br>");
    var full = highlightedContent;
    highlightedContent =
      '<div class="msg-preview">' +
      preview +
      "</div>" +
      '<div class="msg-full" style="display:none">' +
      full +
      "</div>" +
      "<button class=\"msg-fold-btn\" onclick=\"this.previousElementSibling.style.display='block';this.previousElementSibling.previousElementSibling.style.display='none';this.textContent='Show less';var b=this;b.onclick=function(){b.previousElementSibling.style.display='none';b.previousElementSibling.previousElementSibling.style.display='block';b.textContent='Show more (" +
      (lines.length - MAX_LINES) +
      " more lines)';b.onclick=arguments.callee}\">" +
      "Show more (" +
      (lines.length - MAX_LINES) +
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

  var attachmentsHtml = "";
  /* attachments already resolved above (for the empty-content guard) */
  var imageAttachments = attachments.filter(function (att) {
    return att.mime_type && att.mime_type.startsWith("image/") && att.url;
  });
  var imgCount = imageAttachments.length;
  var gridClass =
    imgCount <= 1
      ? "count-1"
      : imgCount === 2
        ? "count-2"
        : imgCount === 3
          ? "count-3"
          : "count-many";
  var imagesHtml = "";
  imageAttachments.forEach(function (att) {
    imagesHtml +=
      '<div class="attachment-img">' +
      '<a href="' +
      escapeHtml(att.url) +
      '" target="_blank">' +
      '<img src="' +
      escapeHtml(att.url) +
      '" alt="' +
      escapeHtml(att.filename || "image") +
      '" loading="lazy"></a></div>';
  });
  if (imgCount > 0) {
    attachmentsHtml +=
      '<div class="attachment-grid ' + gridClass + '">' + imagesHtml + "</div>";
  }
  attachments.forEach(function (att) {
    if (att.mime_type && att.mime_type.startsWith("image/")) {
      /* handled above in grid */
    } else if (att.url) {
      var sizeStr = att.size
        ? " (" +
          (att.size > 1024 * 1024
            ? (att.size / 1024 / 1024).toFixed(1) + " MB"
            : (att.size / 1024).toFixed(0) + " KB") +
          ")"
        : "";
      attachmentsHtml +=
        '<div class="attachment-file">' +
        '<a href="' +
        escapeHtml(att.url) +
        '" target="_blank" download>' +
        "\uD83D\uDCCE " +
        escapeHtml(att.filename || "attachment") +
        escapeHtml(sizeStr) +
        "</a></div>";
    }
  });
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
   * actively typing so we don't yank their viewport either. */
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  container.appendChild(el);
  /* ALWAYS auto-scroll when near the bottom — including when the user is
   * actively typing. Skipping the scroll while focused was too aggressive
   * and broke the "I just sent a message" case (todo#227): the user's own
   * outgoing message stayed below the fold because focus was still on
   * #msg-input. The focus-preserve idiom (save selection → restore after
   * mutation) is sufficient on its own for the typing-mid-incoming case. */
  if (nearBottom) {
    container.scrollTop = container.scrollHeight;
  }
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
  }
  applyIssueTitleHints(el);
}

function filterMessages() {
  var msgs = document.querySelectorAll(".msg");
  msgs.forEach(function (el) {
    if (!currentChannel) {
      el.style.display = "";
    } else {
      var ch = el.getAttribute("data-channel");
      el.style.display = ch === currentChannel ? "" : "none";
    }
  });
}

async function loadHistory() {
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
  var channel = currentChannel || "#general";
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
      input.style.height = Math.min(input.scrollHeight, 120) + "px";
    }
  } catch (_) {}
}
window.restoreDraftForCurrentChannel = restoreDraftForCurrentChannel;
document.getElementById("msg-input").addEventListener("input", function () {
  this.style.height = "auto";
  this.style.height = Math.min(this.scrollHeight, 120) + "px";
  _saveDraft(this.value);
});
restoreDraftForCurrentChannel();

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
  if (e.key === "Enter") {
    var dd = document.getElementById("mention-dropdown");
    if (dd && dd.classList.contains("visible")) return;
    if (e.shiftKey) return;
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
    if (e.key === "Enter" && !e.shiftKey) {
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
  if (!confirm("Delete this message?")) return;
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
    currentChannel = ch;
    if (typeof loadChannelHistory === "function") {
      loadChannelHistory(ch);
    }
    if (typeof addTag === "function") {
      addTag("channel", ch);
    }
  }
});
