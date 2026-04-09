/* Chat module -- message display, history, filtering */
/* globals: escapeHtml, getAgentColor, timeAgo, cachedAgentNames, userName,
   currentChannel, knownMessageKeys, messageKey, sendOrochiMessage,
   updateResourcePanel, token, apiUrl */

function isKnownAgent(name) {
  return cachedAgentNames.indexOf(name) !== -1;
}

/* Cache of GitHub issue titles (number → title) used for hover tooltips */
var issueTitleCache = {};

function applyIssueTitleHints(scope) {
  var root = scope || document;
  root.querySelectorAll(".issue-link").forEach(function (a) {
    /* Parse from the raw number — text may already include an inline title */
    var num = a.getAttribute("data-issue-num");
    if (!num) {
      var m = a.textContent.match(/#(\d+)/);
      if (!m) return;
      num = m[1];
      a.setAttribute("data-issue-num", num);
    }
    var title = issueTitleCache[num];
    if (title && !a.dataset.hinted) {
      a.title = "#" + num + " " + title;
      /* Inline the title so readers can see it without hovering. Kept
       * compact and clipped via CSS so long titles don't wrap the msg. */
      a.innerHTML =
        '#' + num +
        ' <span class="issue-link-title">(' +
        escapeHtml(title) +
        ')</span>';
      a.dataset.hinted = "1";
    }
  });
}

async function refreshIssueTitleCache() {
  try {
    var res = await fetch(apiUrl("/api/github/issues"), { credentials: "same-origin" });
    if (!res.ok) return;
    var issues = await res.json();
    if (Array.isArray(issues)) {
      issues.forEach(function (i) {
        if (i && i.number && i.title) issueTitleCache[String(i.number)] = i.title;
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
  if (!content) return;
  var senderColor = getAgentColor(senderName);
  if (channel) {
    el.setAttribute("data-channel", channel);
  }
  /* Mentions must be highlighted BEFORE the newline→<br> conversion,
   * otherwise a mention sitting right after a line break doesn't match
   * the `(^|[\s])` anchor (since <br> is not whitespace). */
  var highlightedContent = escapeHtml(content)
    .replace(/(^|[\s\r\n])@([\w@.\-]+)/g, function (_match, prefix, name) {
      return prefix + '<span class="mention-highlight">@' + name + "</span>";
    })
    .replace(/\n/g, "<br>")
    .replace(
      /(#(?:general|todo|research|deploy|telegram|orchestrator))\b/g,
      '<span class="channel-highlight">$1</span>',
    )
    .replace(
      /(?<![\/\w])#(\d+)\b/g,
      '<a class="issue-link" href="https://github.com/ywatanabe1989/todo/issues/$1" target="_blank">#$1</a>',
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
  var attachmentsHtml = "";
  /* Attachments may arrive under three shapes depending on path:
   *  - payload.attachments (legacy direct-emit path)
   *  - metadata.attachments (what the WS broadcast now uses)
   *  - top-level attachments (REST history reload)  */
  var attachments =
    (msg.payload && msg.payload.attachments) ||
    (msg.metadata && msg.metadata.attachments) ||
    msg.attachments ||
    [];
  attachments.forEach(function (att) {
    if (att.mime_type && att.mime_type.startsWith("image/")) {
      attachmentsHtml +=
        '<div class="attachment-img">' +
        '<a href="' +
        escapeHtml(att.url) +
        '" target="_blank">' +
        '<img src="' +
        escapeHtml(att.url) +
        '" alt="' +
        escapeHtml(att.filename || "image") +
        '" loading="lazy"></a></div>';
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
    '<span class="channel">' +
    escapeHtml(channel) +
    "</span>" +
    '<span class="ts" title="' +
    escapeHtml(fullTs) +
    '">' +
    ts +
    "</span>" +
    "</div>" +
    '<div class="content">' +
    highlightedContent +
    "</div>" +
    attachmentsHtml +
    (msg.id ? '<div class="msg-reactions" data-msg-id="' + msg.id + '"></div>' : "") +
    (msg.id ? '<button class="msg-react-btn" type="button" title="React" onclick="openReactionPicker(this,' + msg.id + ')">+</button>' : "") +
    (msg.id ? '<button class="msg-thread-btn" type="button" title="Reply in thread" onclick="openThreadForMessage(' + msg.id + ')">\uD83D\uDCAC</button>' : "");
  if (currentChannel && channel !== currentChannel) {
    el.style.display = "none";
  }
  var container = document.getElementById("messages");
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
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
    historyLoaded = true;
    /* Fetch reactions for all loaded messages */
    if (typeof fetchReactionsForMessages === "function") {
      var ids = messages.map(function (r) { return r.id; }).filter(Boolean);
      fetchReactionsForMessages(ids);
    }
  } catch (e) {
    console.error("loadHistory failed:", e);
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
    if (typeof fetchReactionsForMessages === "function") {
      var ids = messages.map(function (r) { return r.id; }).filter(Boolean);
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
  if (typeof clearPendingAttachments === "function") {
    clearPendingAttachments();
  }
}

/* Auto-resize textarea as content grows */
document.getElementById("msg-input").addEventListener("input", function () {
  this.style.height = "auto";
  this.style.height = Math.min(this.scrollHeight, 120) + "px";
});

document.getElementById("msg-send").addEventListener("click", sendMessage);
document.getElementById("msg-input").addEventListener("keydown", function (e) {
  if (e.key === "Enter") {
    var dd = document.getElementById("mention-dropdown");
    if (dd && dd.classList.contains("visible")) return;
    if (e.shiftKey) return;
    e.preventDefault();
    sendMessage();
  }
});

/* Timestamps are now absolute (YYYY-MM-DD HH:mm:ss), no periodic refresh needed */
