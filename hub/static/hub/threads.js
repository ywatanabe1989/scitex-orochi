/* Threading — reply to a message in a thread panel */
/* globals: apiUrl, orochiHeaders, escapeHtml, timeAgo, getAgentColor,
   cleanAgentName, getSenderIcon, getResolvedAgentColor */

var threadPanel = null;
var threadPanelParentId = null;

function closeThreadPanel() {
  if (threadPanel && threadPanel.parentNode) {
    threadPanel.parentNode.removeChild(threadPanel);
  }
  threadPanel = null;
  threadPanelParentId = null;
  /* Restore main area width */
  var mainEl = document.querySelector(".main");
  if (mainEl) mainEl.style.marginRight = "";
}

async function openThreadPanel(parentId) {
  closeThreadPanel();
  threadPanelParentId = parentId;

  /* Build the parent message preview from the DOM */
  var parentPreview = _buildParentPreview(parentId);

  threadPanel = document.createElement("div");
  threadPanel.className = "thread-panel";
  threadPanel.innerHTML =
    '<div class="thread-header">' +
    '<span class="thread-header-title">Thread</span>' +
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
      if (e.key === "Enter" && !e.shiftKey) {
        /* Don't send if mention dropdown is open and an item is selected */
        if (typeof mentionDropdown !== "undefined" && mentionDropdown &&
            mentionDropdown.classList.contains("visible") && mentionSelectedIndex >= 0) {
          return; /* Let handleMentionKeydown handle it */
        }
        e.preventDefault();
        sendThreadReply();
      }
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
          '<div class="thread-reply">' +
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
          escapeHtml(r.content).replace(/\n/g, "<br>") +
          "</div>" +
          "</div>"
        );
      })
      .join("");
    container.scrollTop = container.scrollHeight;
  } catch (e) {
    console.error("loadThreadReplies error:", e);
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
  /* Refresh replies if the thread panel is open for this parent */
  if (threadPanelParentId && msg.parent_id === threadPanelParentId) {
    loadThreadReplies(threadPanelParentId);
  }
  /* Update the thread count badge on the parent message in main feed */
  _incrementThreadCountBadge(msg.parent_id);
}

function _incrementThreadCountBadge(parentId) {
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
}

/* Called from chat.js — opens thread for clicked message */
function openThreadForMessage(messageId) {
  openThreadPanel(messageId);
}
