// @ts-nocheck
import { getResolvedAgentColor, getSenderIcon } from "../agent-icons";
import { apiUrl, cleanAgentName, escapeHtml, getAgentColor, orochiHeaders, timeAgo } from "../app/utils";
import { buildAttachmentsHtml } from "../chat/chat-attachments";
import { initMentionAutocomplete, mentionDropdown, mentionSelectedIndex } from "../mention";
import { openSketch } from "../sketch";
import { _linkifyThreadContent, _pushThreadUrlState, _renderThreadAttachmentTray, _stageThreadFiles } from "./state";

/* Threading — panel open/close, replies render, send, WS handlers */
/* globals: apiUrl, orochiHeaders, escapeHtml, timeAgo, getAgentColor,
   cleanAgentName, getSenderIcon, getResolvedAgentColor,
   (globalThis as any).threadPanel, (globalThis as any).threadPanelParentId, (globalThis as any).threadPendingAttachments,
   (globalThis as any)._threadSketchActive, _renderThreadAttachmentTray, _stageThreadFiles,
   _linkifyThreadContent, _pushThreadUrlState */

export function closeThreadPanel(opts) {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  if ((globalThis as any).threadPanel && (globalThis as any).threadPanel.parentNode) {
    (globalThis as any).threadPanel.parentNode.removeChild((globalThis as any).threadPanel);
  }
  (globalThis as any).threadPanel = null;
  (globalThis as any).threadPanelParentId = null;
  if (!(opts && opts.skipPushState)) {
    _pushThreadUrlState(null);
  }
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
}

export async function openThreadPanel(parentId, opts) {
  closeThreadPanel({ skipPushState: true });
  (globalThis as any).threadPanelParentId = parentId;
  if (!(opts && opts.skipPushState)) {
    _pushThreadUrlState(parentId);
  }

  /* Build the parent message preview from the DOM */
  var parentPreview = _buildParentPreview(parentId);

  (globalThis as any).threadPanel = document.createElement("div");
  (globalThis as any).threadPanel.className = "thread-panel";
  (globalThis as any).threadPanel.innerHTML =
    '<div class="thread-header">' +
    '<button type="button" class="thread-back" onclick="closeThreadPanel()" aria-label="Back to chat">' +
    '<span class="thread-back-arrow">\u2190</span>' +
    '<span class="thread-back-label">Back</span>' +
    "</button>" +
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
    '<div id="thread-pending-attachments" class="thread-pending-attachments" style="display:none"></div>' +
    '<div class="thread-compose-row">' +
    '<textarea id="thread-input" placeholder="Reply in thread…" rows="2"></textarea>' +
    '<div class="thread-bottom-row">' +
    '<div class="thread-input-actions">' +
    '<button type="button" id="thread-attach-btn" tabindex="-1" title="Attach file (Ctrl+U)">📎</button>' +
    '<button type="button" id="thread-sketch-btn" tabindex="-1" title="Draw sketch">✏️</button>' +
    '<button type="button" id="thread-voice-btn" tabindex="-1" title="Voice input">🎤</button>' +
    '<button type="button" id="thread-voice-lang-btn" tabindex="-1" title="Switch language (EN/JA)" style="font-size:11px;padding:2px 5px;opacity:0.7;">EN</button>' +
    '<input type="file" id="thread-file-input" style="display:none" multiple>' +
    "</div>" +
    '<button type="button" class="thread-send-btn" onclick="sendThreadReply()">Send</button>' +
    "</div>" +
    "</div>" +
    "</div>";
  /* Append as flex sibling of .main inside .container (Slack-style side-by-side) */
  var container = document.querySelector(".container");
  if (container) {
    container.appendChild((globalThis as any).threadPanel);
  } else {
    document.body.appendChild((globalThis as any).threadPanel);
  }

  await loadThreadReplies(parentId);
  var ta = document.getElementById("thread-input");
  if (ta) {
    ta.focus();
    ta.addEventListener("keydown", function (e) {
      /* Alt+Enter / Ctrl+Enter in thread: toggle voice directed at thread textarea */
      if (e.key === "Enter" && (e.altKey || e.ctrlKey)) {
        e.preventDefault();
        e.stopPropagation(); /* prevent global voice handler from double-firing */
        if (typeof window.toggleVoiceInput === "function") {
          /* Focus thread textarea so _toggleVoice captures it as target */
          var tIn = document.getElementById("thread-input");
          if (tIn) tIn.focus();
          window.toggleVoiceInput();
        }
        return;
      }
      /* Plain Enter (no modifier) sends reply */
      if (e.key === "Enter" && !e.shiftKey) {
        /* Don't send if mention dropdown is open and an item is selected */
        if (
          typeof mentionDropdown !== "undefined" &&
          mentionDropdown &&
          mentionDropdown.classList.contains("visible") &&
          mentionSelectedIndex >= 0
        ) {
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
    /* Ctrl+U → trigger file picker in thread panel */
    ta.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key === "u") {
        e.preventDefault();
        var fi = document.getElementById("thread-file-input");
        if (fi) fi.click();
      }
    });
  }

  /* Wire thread action buttons */
  (globalThis as any).threadPendingAttachments = [];
  _renderThreadAttachmentTray();

  var attachBtn = document.getElementById("thread-attach-btn");
  var fileInput = document.getElementById("thread-file-input");
  var sketchBtn = document.getElementById("thread-sketch-btn");
  var voiceBtn = document.getElementById("thread-voice-btn");
  var voiceLangBtn = document.getElementById("thread-voice-lang-btn");

  if (attachBtn && fileInput) {
    attachBtn.addEventListener("click", function () {
      fileInput.click();
    });
    fileInput.addEventListener("change", function () {
      _stageThreadFiles(Array.from(fileInput.files || []));
      fileInput.value = "";
    });
  }

  if (sketchBtn) {
    sketchBtn.addEventListener("click", function () {
      /* openSketch() sends to currentChannel; we override the callback */
      if (typeof openSketch === "function") {
        (globalThis as any)._threadSketchActive = true;
        openSketch();
      }
    });
  }

  if (voiceBtn) {
    /* Toggle voice into the thread textarea */
    voiceBtn.addEventListener("click", function () {
      if (typeof window.toggleVoiceInput === "function") {
        /* Focus thread textarea so _toggleVoice captures it as target */
        var tIn = document.getElementById("thread-input");
        if (tIn) tIn.focus();
        window.toggleVoiceInput();
      }
    });
  }

  if (voiceLangBtn) {
    /* Sync button label with voice-input.js current language on open */
    var mainLangBtn = document.getElementById("msg-voice-lang");
    if (mainLangBtn) voiceLangBtn.textContent = mainLangBtn.textContent;
    voiceLangBtn.addEventListener("click", function () {
      if (typeof window.cycleVoiceLang === "function") {
        window.cycleVoiceLang();
        /* Sync label from main lang button */
        if (mainLangBtn) voiceLangBtn.textContent = mainLangBtn.textContent;
      }
    });
  }
}

export function _buildParentPreview(parentId) {
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
  /* Use innerHTML so the already-rendered markdown/code/links are preserved (#385) */
  var contentHtml = contentEl ? contentEl.innerHTML : "";
  var tsText = tsEl ? tsEl.textContent : "";
  var senderColor =
    typeof getResolvedAgentColor === "function"
      ? getResolvedAgentColor(senderName)
      : typeof getAgentColor === "function"
        ? getAgentColor(senderName)
        : "#aaa";
  var senderIcon =
    typeof getSenderIcon === "function" ? getSenderIcon(senderName, true) : "";

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
    contentHtml +
    "</div>"
  );
}

export async function loadThreadReplies(parentId) {
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
          (typeof buildAttachmentsHtml === "function"
            ? buildAttachmentsHtml((r.metadata && r.metadata.attachments) || [])
            : "") +
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
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
}

export async function sendThreadReply() {
  if (!(globalThis as any).threadPanelParentId) return;
  var ta = document.getElementById("thread-input");
  if (!ta) return;
  var text = ta.value.trim();
  var attachments = (globalThis as any).threadPendingAttachments
    .filter(function (p) {
      return p.uploaded;
    })
    .map(function (p) {
      return p.uploaded;
    });
  if (!text && !attachments.length) return;
  ta.value = "";
  ta.style.height = "auto";
  /* Reset voice input so it doesn't re-fill the textarea with old text */
  if (typeof window.voiceInputResetAfterSend === "function") {
    try {
      window.voiceInputResetAfterSend();
    } catch (_) {}
  }
  /* Clear thread attachment tray */
  (globalThis as any).threadPendingAttachments = [];
  _renderThreadAttachmentTray();
  try {
    var res = await fetch(apiUrl("/api/threads/"), {
      method: "POST",
      headers: orochiHeaders(),
      credentials: "same-origin",
      body: JSON.stringify({
        parent_id: (globalThis as any).threadPanelParentId,
        text: text,
        attachments: attachments,
      }),
    });
    if (!res.ok) {
      console.error("sendThreadReply failed:", res.status);
      return;
    }
    /* WS broadcast will refresh the panel; also optimistic reload */
    loadThreadReplies((globalThis as any).threadPanelParentId);
  } catch (e) {
    console.error("sendThreadReply error:", e);
  }
}

/* Called from app.js on thread_reply WS events */
export function handleThreadReply(msg) {
  /* Append incrementally to open thread panel (with dedupe) */
  if ((globalThis as any).threadPanelParentId && msg.parent_id === (globalThis as any).threadPanelParentId) {
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
export function appendToThreadPanelIfOpen(msg) {
  if (!(globalThis as any).threadPanelParentId) return;
  var meta =
    (msg && ((msg.payload && msg.payload.metadata) || msg.metadata)) || {};
  var replyTo = meta.reply_to;
  if (replyTo == null) return;
  /* Coerce both sides to number for comparison (metadata may be string) */
  if (Number(replyTo) !== Number((globalThis as any).threadPanelParentId)) return;
  _appendReplyToPanel({
    id: msg.id,
    sender: msg.sender,
    sender_type: msg.sender_type,
    content:
      msg.text ||
      (msg.payload && (msg.payload.content || msg.payload.text)) ||
      "",
    ts: msg.ts,
  });
  _incrementThreadCountBadge((globalThis as any).threadPanelParentId);
}

export function _appendReplyToPanel(r) {
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
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
}

export function _incrementThreadCountBadge(parentId) {
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
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
}

/* Called from chat.js — opens thread for clicked message */
export function openThreadForMessage(messageId) {
  openThreadPanel(messageId);
}
