/* Threading — reply to a message in a thread panel */
/* globals: apiUrl, orochiHeaders, escapeHtml, timeAgo, getAgentColor, cleanAgentName */

var threadPanel = null;
var threadPanelParentId = null;

function closeThreadPanel() {
  if (threadPanel && threadPanel.parentNode) {
    threadPanel.parentNode.removeChild(threadPanel);
  }
  threadPanel = null;
  threadPanelParentId = null;
}

async function openThreadPanel(parentId) {
  closeThreadPanel();
  threadPanelParentId = parentId;
  threadPanel = document.createElement("div");
  threadPanel.className = "thread-panel";
  threadPanel.innerHTML =
    '<div class="thread-header">' +
    '<span>Thread</span>' +
    '<button type="button" class="thread-close" onclick="closeThreadPanel()">&times;</button>' +
    '</div>' +
    '<div class="thread-replies" id="thread-replies"></div>' +
    '<div class="thread-input-row">' +
    '<textarea id="thread-input" placeholder="Reply in thread..." rows="2"></textarea>' +
    '<button type="button" class="thread-send-btn" onclick="sendThreadReply()">Send</button>' +
    '</div>';
  document.body.appendChild(threadPanel);
  await loadThreadReplies(parentId);
  var ta = document.getElementById("thread-input");
  if (ta) {
    ta.focus();
    ta.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendThreadReply();
      }
    });
  }
}

async function loadThreadReplies(parentId) {
  var container = document.getElementById("thread-replies");
  if (!container) return;
  try {
    var res = await fetch(apiUrl("/api/threads/?parent_id=" + parentId), {
      credentials: "same-origin",
    });
    if (!res.ok) {
      container.innerHTML = '<p class="empty-notice">Failed to load thread.</p>';
      return;
    }
    var replies = await res.json();
    if (replies.length === 0) {
      container.innerHTML = '<p class="empty-notice">No replies yet.</p>';
      return;
    }
    container.innerHTML = replies.map(function (r) {
      var color = getAgentColor(r.sender);
      return (
        '<div class="thread-reply">' +
        '<div class="thread-reply-header">' +
        '<span class="sender" style="color:' + color + '">' +
        escapeHtml(cleanAgentName(r.sender)) +
        '</span>' +
        ' <span class="ts">' + escapeHtml(timeAgo(r.ts) || "") + '</span>' +
        '</div>' +
        '<div class="thread-reply-body">' + escapeHtml(r.content).replace(/\n/g, "<br>") + '</div>' +
        '</div>'
      );
    }).join("");
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
  if (threadPanelParentId && msg.parent_id === threadPanelParentId) {
    loadThreadReplies(threadPanelParentId);
  }
}

/* Called from chat.js — opens thread for clicked message */
function openThreadForMessage(messageId) {
  openThreadPanel(messageId);
}
