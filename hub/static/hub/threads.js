/* Threading — reply to a message in a thread panel */
/* globals: apiUrl, orochiHeaders, escapeHtml, timeAgo, getAgentColor,
   cleanAgentName, getSenderIcon, getResolvedAgentColor */

var threadPanel = null;
var threadPanelParentId = null;

/* Auto-link URLs in already-escaped HTML (applied to thread reply bodies). */
function _linkifyThreadContent(html) {
  return html.replace(
    /(?<!["'=])(https?:\/\/[^\s<>"')\]]+)/g,
    '<a class="chat-link" href="$1" target="_blank" rel="noopener">$1</a>',
  );
}

/* Build a permalink URL for a thread parent message. */
function threadPermalinkUrl(parentId) {
  return (
    window.location.origin +
    window.location.pathname +
    "?thread=" +
    encodeURIComponent(String(parentId))
  );
}

/* Copy a permalink to the clipboard and flash a "Copied!" tooltip on the
 * triggering button.  Never steals focus from #msg-input (todo#225). */
function copyThreadPermalink(parentId, btnEl) {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var url = threadPermalinkUrl(parentId);
  var done = function () {
    if (btnEl) {
      var prev = btnEl.getAttribute("data-prev-title") || btnEl.title || "";
      btnEl.setAttribute("data-prev-title", prev);
      btnEl.classList.add("permalink-copied");
      btnEl.title = "Copied!";
      setTimeout(function () {
        btnEl.classList.remove("permalink-copied");
        btnEl.title = prev;
      }, 1500);
    }
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
    }
  };
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(done, done);
    } else {
      var ta = document.createElement("textarea");
      ta.value = url;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); } catch (_) {}
      document.body.removeChild(ta);
      done();
    }
  } catch (_) {
    done();
  }
}

/* Update window.location to reflect whether a thread is open.  Uses
 * history.pushState so the back button works naturally. */
function _pushThreadUrlState(parentId) {
  try {
    var url;
    if (parentId == null) {
      url = window.location.pathname + window.location.hash;
    } else {
      url =
        window.location.pathname +
        "?thread=" +
        encodeURIComponent(String(parentId)) +
        window.location.hash;
    }
    window.history.pushState({ thread: parentId }, "", url);
  } catch (_) {}
}

function _readThreadIdFromUrl() {
  try {
    var sp = new URLSearchParams(window.location.search);
    var v = sp.get("thread");
    if (v == null || v === "") return null;
    var n = Number(v);
    return isFinite(n) && n > 0 ? n : null;
  } catch (_) {
    return null;
  }
}

/* Auto-open the thread panel for ?thread=<id> on initial page load.
 * Called from chat.js#loadHistory() after messages are rendered. */
function applyThreadUrlOnLoad() {
  var id = _readThreadIdFromUrl();
  if (id == null) return;
  if (threadPanelParentId === id) return;
  openThreadPanel(id, { skipPushState: true });
}

/* popstate — user hit back/forward; sync the panel to whatever the URL
 * now says. */
window.addEventListener("popstate", function () {
  var id = _readThreadIdFromUrl();
  if (id == null) {
    if (threadPanel) closeThreadPanel({ skipPushState: true });
  } else if (threadPanelParentId !== id) {
    openThreadPanel(id, { skipPushState: true });
  }
});

function closeThreadPanel(opts) {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  if (threadPanel && threadPanel.parentNode) {
    threadPanel.parentNode.removeChild(threadPanel);
  }
  threadPanel = null;
  threadPanelParentId = null;
  /* Restore main area width */
  var mainEl = document.querySelector(".main");
  if (mainEl) mainEl.style.marginRight = "";
  if (!(opts && opts.skipPushState)) {
    _pushThreadUrlState(null);
  }
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
  }
}

async function openThreadPanel(parentId, opts) {
  closeThreadPanel({ skipPushState: true });
  threadPanelParentId = parentId;
  if (!(opts && opts.skipPushState)) {
    _pushThreadUrlState(parentId);
  }

  /* Build the parent message preview from the DOM */
  var parentPreview = _buildParentPreview(parentId);

  threadPanel = document.createElement("div");
  threadPanel.className = "thread-panel";
  threadPanel.innerHTML =
    '<div class="thread-header">' +
    '<button type="button" class="thread-back" onclick="closeThreadPanel()" aria-label="Back to chat">' +
    '<span class="thread-back-arrow">\u2190</span>' +
    '<span class="thread-back-label">Back</span>' +
    '</button>' +
    '<span class="thread-header-title">Thread</span>' +
    '<button type="button" class="permalink-btn thread-permalink-btn" tabindex="-1" ' +
    'title="Copy link to this thread" ' +
    'onclick="event.stopPropagation();copyThreadPermalink(' +
    String(parentId) +
    ',this)">\uD83D\uDD17</button>' +
    '<button type="button" class="thread-close" onclick="closeThreadPanel()">&times;</button>' +
    "</div>" +
    '<div class="thread-parent-msg">' +
    parentPreview +
    "</div>" +
    '<div class="thread-divider"><span class="thread-divider-text">Replies</span></div>' +
    '<div class="thread-replies" id="thread-replies"></div>' +
    '<div class="thread-input-row">' +
    '<textarea id="thread-input" placeholder="Reply in thread..." rows="2"></textarea>' +
    '<button type="button" class="thread-send-btn" onclick="sendThreadReply()">Send</button>' +
    "</div>";
  document.body.appendChild(threadPanel);

  /* Shrink main area so thread panel doesn't overlap */
  var mainEl = document.querySelector(".main");
  if (mainEl) mainEl.style.marginRight = "360px";

  await loadThreadReplies(parentId);
  var ta = document.getElementById("thread-input");
  if (ta) {
    ta.focus();
    ta.addEventListener("keydown", function (e) {
      /* todo#332: Shift+Enter and Alt+Enter both insert a newline */
      if (e.key === "Enter" && !e.shiftKey && !e.altKey) {
        /* Don't send if mention dropdown is open and an item is selected */
        if (typeof mentionDropdown !== "undefined" && mentionDropdown &&
            mentionDropdown.classList.contains("visible") && mentionSelectedIndex >= 0) {
          return; /* Let handleMentionKeydown handle it */
        }
        e.preventDefault();
        sendThreadReply();
      }
    });
    /* Auto-resize: grow with content up to 120px */
    ta.addEventListener("input", function () {
      this.style.height = "auto";
      this.style.height = Math.min(this.scrollHeight, 120) + "px";
    });
    /* Enable @mention autocomplete in thread input */
    if (typeof initMentionAutocomplete === "function") {
      initMentionAutocomplete(ta);
    }
  }
}

function _buildParentPreview(parentId) {
  var parentEl = document.querySelector(
    '.msg[data-msg-id="' + String(parentId) + '"]',
  );
  if (!parentEl) {
    return (
      '<div class="thread-parent-placeholder">Message #' + parentId + "</div>"
    );
  }
  var senderEl = parentEl.querySelector(".sender");
  var contentEl = parentEl.querySelector(".content");
  var tsEl = parentEl.querySelector(".ts");
  var senderName = senderEl ? senderEl.textContent : "unknown";
  var content = contentEl ? contentEl.textContent : "";
  var tsText = tsEl ? tsEl.textContent : "";
  var senderColor =
    typeof getResolvedAgentColor === "function"
      ? getResolvedAgentColor(senderName)
      : typeof getAgentColor === "function"
        ? getAgentColor(senderName)
        : "#aaa";
  var senderIcon =
    typeof getSenderIcon === "function" ? getSenderIcon(senderName, true) : "";

  /* Truncate long parent content */
  var maxLen = 300;
  var truncated =
    content.length > maxLen ? content.slice(0, maxLen) + "..." : content;

  return (
    '<div class="thread-parent-header">' +
    '<span class="msg-icon">' +
    senderIcon +
    "</span>" +
    '<span class="sender" style="color:' +
    senderColor +
    '">' +
    escapeHtml(
      typeof cleanAgentName === "function"
        ? cleanAgentName(senderName)
        : senderName,
    ) +
    "</span>" +
    '<span class="ts">' +
    escapeHtml(tsText) +
    "</span>" +
    "</div>" +
    '<div class="thread-parent-body">' +
    escapeHtml(truncated).replace(/\n/g, "<br>") +
    "</div>"
  );
}

async function loadThreadReplies(parentId) {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var container = document.getElementById("thread-replies");
  if (!container) return;
  try {
    var res = await fetch(apiUrl("/api/threads/?parent_id=" + parentId), {
      credentials: "same-origin",
    });
    if (!res.ok) {
      container.innerHTML =
        '<p class="empty-notice">Failed to load thread.</p>';
      return;
    }
    var replies = await res.json();
    if (replies.length === 0) {
      container.innerHTML =
        '<p class="empty-notice">No replies yet. Be the first to reply.</p>';
      return;
    }
    container.innerHTML = replies
      .map(function (r) {
        var color =
          typeof getResolvedAgentColor === "function"
            ? getResolvedAgentColor(r.sender)
            : typeof getAgentColor === "function"
              ? getAgentColor(r.sender)
              : "#aaa";
        var icon =
          typeof getSenderIcon === "function"
            ? getSenderIcon(r.sender, r.sender_type === "agent")
            : "";
        return (
          '<div class="thread-reply" data-reply-id="' +
          String(r.id) +
          '">' +
          '<div class="thread-reply-header">' +
          '<span class="msg-icon">' +
          icon +
          "</span>" +
          '<span class="sender" style="color:' +
          color +
          '">' +
          escapeHtml(
            typeof cleanAgentName === "function"
              ? cleanAgentName(r.sender)
              : r.sender,
          ) +
          "</span>" +
          ' <span class="ts">' +
          escapeHtml(timeAgo(r.ts) || "") +
          "</span>" +
          "</div>" +
          '<div class="thread-reply-body">' +
          _linkifyThreadContent(escapeHtml(r.content).replace(/\n/g, "<br>")) +
          "</div>" +
          "</div>"
        );
      })
      .join("");
    container.scrollTop = container.scrollHeight;
  } catch (e) {
    console.error("loadThreadReplies error:", e);
  }
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
  }
}

async function sendThreadReply() {
  if (!threadPanelParentId) return;
  var ta = document.getElementById("thread-input");
  if (!ta) return;
  var text = ta.value.trim();
  if (!text) return;
  ta.value = "";
  try {
    var res = await fetch(apiUrl("/api/threads/"), {
      method: "POST",
      headers: orochiHeaders(),
      credentials: "same-origin",
      body: JSON.stringify({ parent_id: threadPanelParentId, text: text }),
    });
    if (!res.ok) {
      console.error("sendThreadReply failed:", res.status);
      return;
    }
    /* WS broadcast will refresh the panel; also optimistic reload */
    loadThreadReplies(threadPanelParentId);
  } catch (e) {
    console.error("sendThreadReply error:", e);
  }
}

/* Called from app.js on thread_reply WS events */
function handleThreadReply(msg) {
  /* Append incrementally to open thread panel (with dedupe) */
  if (threadPanelParentId && msg.parent_id === threadPanelParentId) {
    _appendReplyToPanel({
      id: msg.reply_id,
      sender: msg.sender,
      sender_type: msg.sender_type,
      content: msg.text || "",
      ts: msg.ts,
    });
  }
  /* Update the thread count badge on the parent message in main feed */
  _incrementThreadCountBadge(msg.parent_id);
}

/* Called from app.js handleMessage for regular chat.message events that
 * carry metadata.reply_to — live-append the reply into an open thread
 * panel whose parent matches. Deduped by data-reply-id so it is safe if
 * the same message also arrived via a thread_reply WS event. */
function appendToThreadPanelIfOpen(msg) {
  if (!threadPanelParentId) return;
  var meta = (msg && ((msg.payload && msg.payload.metadata) || msg.metadata)) || {};
  var replyTo = meta.reply_to;
  if (replyTo == null) return;
  /* Coerce both sides to number for comparison (metadata may be string) */
  if (Number(replyTo) !== Number(threadPanelParentId)) return;
  _appendReplyToPanel({
    id: msg.id,
    sender: msg.sender,
    sender_type: msg.sender_type,
    content: msg.text || (msg.payload && (msg.payload.content || msg.payload.text)) || "",
    ts: msg.ts,
  });
  _incrementThreadCountBadge(threadPanelParentId);
}

function _appendReplyToPanel(r) {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var container = document.getElementById("thread-replies");
  if (!container) return;
  /* Dedupe by reply id */
  if (r.id != null) {
    var existing = container.querySelector(
      '.thread-reply[data-reply-id="' + String(r.id) + '"]',
    );
    if (existing) return;
  }
  /* Replace empty-notice placeholder on first live append */
  var emptyEl = container.querySelector(".empty-notice");
  if (emptyEl) emptyEl.remove();

  var color =
    typeof getResolvedAgentColor === "function"
      ? getResolvedAgentColor(r.sender)
      : typeof getAgentColor === "function"
        ? getAgentColor(r.sender)
        : "#aaa";
  var icon =
    typeof getSenderIcon === "function"
      ? getSenderIcon(r.sender, r.sender_type === "agent")
      : "";
  var wrap = document.createElement("div");
  wrap.className = "thread-reply";
  if (r.id != null) wrap.setAttribute("data-reply-id", String(r.id));
  wrap.innerHTML =
    '<div class="thread-reply-header">' +
    '<span class="msg-icon">' + icon + "</span>" +
    '<span class="sender" style="color:' + color + '">' +
    escapeHtml(
      typeof cleanAgentName === "function" ? cleanAgentName(r.sender) : r.sender,
    ) +
    "</span>" +
    ' <span class="ts">' +
    escapeHtml((typeof timeAgo === "function" && timeAgo(r.ts)) || "") +
    "</span>" +
    "</div>" +
    '<div class="thread-reply-body">' +
    _linkifyThreadContent(escapeHtml(r.content || "").replace(/\n/g, "<br>")) +
    "</div>";
  container.appendChild(wrap);
  /* Smooth scroll to newest reply */
  container.scrollTop = container.scrollHeight;
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
  }
}

function _incrementThreadCountBadge(parentId) {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var badge = document.querySelector(
    '.msg-thread-count[data-msg-id="' + parentId + '"]',
  );
  if (badge) {
    /* Parse current count and increment */
    var m = badge.textContent.match(/(\d+)/);
    var count = m ? parseInt(m[1], 10) + 1 : 1;
    badge.textContent =
      "\uD83D\uDCAC " + count + (count === 1 ? " reply" : " replies");
  } else {
    /* No badge yet — create one on the parent message element */
    var parentEl = document.querySelector(
      '.msg[data-msg-id="' + parentId + '"]',
    );
    if (parentEl) {
      var newBadge = document.createElement("div");
      newBadge.className = "msg-thread-count";
      newBadge.setAttribute("data-msg-id", String(parentId));
      newBadge.onclick = function () {
        openThreadForMessage(parentId);
      };
      newBadge.textContent = "\uD83D\uDCAC 1 reply";
      parentEl.appendChild(newBadge);
    }
  }
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
  }
}

/* Called from chat.js — opens thread for clicked message */
function openThreadForMessage(messageId) {
  openThreadPanel(messageId);
}
