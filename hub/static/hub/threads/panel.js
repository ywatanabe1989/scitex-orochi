/* Threading — panel open/close, replies render, send, WS handlers.
 * Reply composer (textarea + attach/sketch/voice/send buttons) is
 * provided by composer.js::renderComposer(surface: "reply") since the
 * SSoT unification. This file owns the surrounding chrome (header,
 * parent preview, replies list, pending-attachments tray) plus the
 * thread-specific voice-lang button sync + draft-store hydration. */
/* globals: apiUrl, orochiHeaders, escapeHtml, timeAgo, getAgentColor,
   cleanAgentName, getSenderIcon, getResolvedAgentColor, renderComposer,
   threadPanel, threadPanelParentId,
   _threadSketchActive, _renderThreadAttachmentTray, _stageThreadFiles,
   getThreadPendingAttachments, resetThreadPendingAttachments,
   _linkifyThreadContent, _pushThreadUrlState */

var _threadComposer = null;

function closeThreadPanel(opts) {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  if (_threadComposer) {
    try { _threadComposer.destroy(); } catch (_) {}
    _threadComposer = null;
  }
  if (threadPanel && threadPanel.parentNode) {
    threadPanel.parentNode.removeChild(threadPanel);
  }
  threadPanel = null;
  threadPanelParentId = null;
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
    '<div class="thread-compose-row" id="thread-composer-slot"></div>' +
    "</div>";
  var container = document.querySelector(".container");
  if (container) {
    container.appendChild(threadPanel);
  } else {
    document.body.appendChild(threadPanel);
  }

  await loadThreadReplies(parentId);

  var composerSlot = document.getElementById("thread-composer-slot");
  /* msg#16527: clear IN PLACE so the shared reference stays authoritative. */
  resetThreadPendingAttachments();
  _renderThreadAttachmentTray();

  if (composerSlot && typeof renderComposer === "function") {
    _threadComposer = renderComposer(composerSlot, {
      surface: "reply",
      placeholder: "Reply in thread\u2026",
      stageFiles: function (files) {
        return _stageThreadFiles(files);
      },
      onSketchOpen: function () {
        _threadSketchActive = true;
      },
      features: {
        mention: true,
        paste: true,
        dragDrop: false,
        attach: true,
        camera: false,
        sketch: true,
        voice: true,
        sendButton: true,
        cmdEnterSubmit: true,
        shiftEnterNewline: true,
        autoResize: true,
        tabAwareFocus: false,
        localVoiceChord: true,
      },
      maxResizePx: 120,
      onSubmit: function () {
        sendThreadReply();
      },
    });

    var ta = _threadComposer.input;
    ta.classList.add("thread-textarea");
    var sendBtn = composerSlot.querySelector(".composer-btn-send");
    if (sendBtn) sendBtn.classList.add("thread-send-btn");

    /* msg#16324: hydrate any persisted thread-reply draft. */
    try {
      if (window.orochiDraftStore) {
        var _saved = window.orochiDraftStore.loadDraft(
          "thread",
          "msg" + String(parentId),
        );
        if (_saved && !ta.value) {
          ta.value = _saved;
          ta.style.height = "auto";
          ta.style.height = Math.min(ta.scrollHeight, 120) + "px";
        }
      }
    } catch (_) {}
    try { ta.focus(); } catch (_) {}
    try {
      var _len = ta.value ? ta.value.length : 0;
      ta.setSelectionRange(_len, _len);
    } catch (_) {}

    /* Persist every keystroke (debounced at 300ms via draft-store). */
    ta.addEventListener("input", function () {
      try {
        if (window.orochiDraftStore) {
          window.orochiDraftStore._debounceSave(
            "thread",
            "msg" + String(threadPanelParentId),
            this.value,
          );
        }
      } catch (_) {}
    });

    var voiceLangBtn = document.getElementById("thread-voice-lang-btn");
    if (voiceLangBtn) {
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

async function sendThreadReply() {
  if (!threadPanelParentId) return;
  var ta = document.getElementById("thread-input");
  if (!ta) return;
  var text = ta.value.trim();
  /* msg#16527: read via the shared accessor so the mirror stays
   * aligned with threads/state — panel.js used to reassign
   * threadPendingAttachments on every open, which the ES-module build
   * cannot do across module boundaries. */
  var attachments = getThreadPendingAttachments()
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
  /* Clear thread attachment tray — in-place mutate (msg#16527). */
  resetThreadPendingAttachments();
  _renderThreadAttachmentTray();
  try {
    var res = await fetch(apiUrl("/api/threads/"), {
      method: "POST",
      headers: orochiHeaders(),
      credentials: "same-origin",
      body: JSON.stringify({
        parent_id: threadPanelParentId,
        text: text,
        attachments: attachments,
      }),
    });
    if (!res.ok) {
      console.error("sendThreadReply failed:", res.status);
      return;
    }
    /* msg#16324: drop the per-thread draft now that the reply landed. */
    try {
      if (window.orochiDraftStore) {
        window.orochiDraftStore.clearDraft(
          "thread",
          "msg" + String(threadPanelParentId),
        );
      }
    } catch (_) {}
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
  var meta =
    (msg && ((msg.payload && msg.payload.metadata) || msg.metadata)) || {};
  var replyTo = meta.reply_to;
  if (replyTo == null) return;
  /* Coerce both sides to number for comparison (metadata may be string) */
  if (Number(replyTo) !== Number(threadPanelParentId)) return;
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
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
}

/* Called from chat.js — opens thread for clicked message */
function openThreadForMessage(messageId) {
  openThreadPanel(messageId);
}
