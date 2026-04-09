/* Chat module -- message display, history, filtering */
/* globals: escapeHtml, getAgentColor, timeAgo, cachedAgentNames, userName,
   currentChannel, knownMessageKeys, messageKey, sendOrochiMessage,
   updateResourcePanel, token, apiUrl */

function isKnownAgent(name) {
  return cachedAgentNames.indexOf(name) !== -1;
}

function appendMessage(msg) {
  var el = document.createElement("div");
  var senderName = msg.sender || "unknown";
  var isAgent = msg.sender_type === "agent" || isKnownAgent(senderName);
  el.className = "msg" + (isAgent ? "" : " msg-human");
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
  var highlightedContent = escapeHtml(content)
    .replace(/\n/g, "<br>")
    .replace(/(^|[\s])@([\w@.\-]+)/g, function (_match, prefix, name) {
      var isSpecial = name === "all" || name === "channel" || name === "agents";
      var isAgent = cachedAgentNames.indexOf(name) !== -1;
      if (isSpecial || isAgent) {
        return prefix + '<span class="mention-highlight">@' + name + "</span>";
      }
      return prefix + "@" + name;
    })
    .replace(
      /(#(?:general|todo|research|deploy|telegram|orchestrator))\b/g,
      '<span class="channel-highlight">$1</span>',
    )
    .replace(
      /(?<![\/\w])#(\d+)\b/g,
      '<a class="issue-link" href="https://github.com/ywatanabe1989/todo/issues/$1" target="_blank">#$1</a>',
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
  var attachments =
    (msg.payload && msg.payload.attachments) || msg.attachments || [];
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
    attachmentsHtml;
  if (currentChannel && channel !== currentChannel) {
    el.style.display = "none";
  }
  var container = document.getElementById("messages");
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
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
        type: "message",
        sender: row.sender,
        sender_type: row.sender_type,
        ts: row.ts,
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
        type: "message",
        sender: row.sender,
        sender_type: row.sender_type,
        ts: row.ts,
        payload: {
          channel: channel,
          content: row.content,
          attachments:
            (row.metadata && row.metadata.attachments) || row.attachments || [],
        },
      });
    });
    container.scrollTop = container.scrollHeight;
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
  if (!text) return;

  /* Prefer WebSocket send when connected (instant echo), fall back to REST */
  if (wsConnected && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(
      JSON.stringify({
        type: "message",
        payload: { channel: channel, content: text },
      }),
    );
  } else {
    sendOrochiMessage({
      type: "message",
      sender: userName,
      payload: { channel: channel, content: text },
    });
  }
  input.value = "";
  input.style.height = "auto";
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
