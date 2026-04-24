// @ts-nocheck
import { getResolvedAgentColor, getSenderIcon } from "../agent-icons";
import { apiUrl, cleanAgentName, escapeHtml, getAgentColor, orochiHeaders, timeAgo } from "../app/utils";
import { buildAttachmentsHtml } from "../chat/chat-attachments";
import { renderComposer } from "../composer/composer";
import {
  _linkifyThreadContent,
  _pushThreadUrlState,
  _renderThreadAttachmentTray,
  _stageThreadFiles,
  getThreadPendingAttachments,
  resetThreadPendingAttachments,
} from "./state";
import { _debounceSave, clearDraft, loadDraft } from "../composer/draft-store";

function _threadDraftTarget(parentId) {
  return "msg" + String(parentId);
}

/* Thread composer instance — created in openThreadPanel, destroyed in
 * closeThreadPanel. Module-scoped so both paths can reference it
 * without a DOM round-trip. */
var _threadComposer = null;

/* Monotonic open-token guarding openThreadPanel against re-entrancy
 * (msg#17058). Rapid re-opens — double-click the reply icon, popstate
 * during an in-flight open, WS-triggered refresh racing a click —
 * used to interleave so two `renderComposer` calls landed in the same
 * #thread-composer-slot (bug A: stacked compose inputs) and a stale
 * `loadThreadReplies` awaited fetch wrote into a detached panel
 * (bug B: replies invisible). Each openThreadPanel bumps this token
 * and stashes a local copy; any continuation after `await` checks the
 * copy against the live token and bails if newer. */
var _threadOpenToken = 0;

/* Threading — panel open/close, replies render, send, WS handlers.
 * Reply composer (textarea + attach/sketch/voice/send buttons) is
 * provided by composer.ts::renderComposer(surface: "reply") since the
 * SSoT unification (msg#16286); this file owns the surrounding chrome
 * (header, parent preview, replies list, pending-attachments tray)
 * plus the thread-specific voice-lang button sync + draft-store
 * hydration. */
/* globals: apiUrl, orochiHeaders, escapeHtml, timeAgo, getAgentColor,
   cleanAgentName, getSenderIcon, getResolvedAgentColor,
   (globalThis as any).threadPanel, (globalThis as any).threadPanelParentId,
   (globalThis as any)._threadSketchActive, _renderThreadAttachmentTray, _stageThreadFiles,
   getThreadPendingAttachments, resetThreadPendingAttachments,
   _linkifyThreadContent, _pushThreadUrlState */

export function closeThreadPanel(opts) {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  if (_threadComposer) {
    try { _threadComposer.destroy(); } catch (_) {}
    _threadComposer = null;
  }
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
  /* Invalidate any in-flight openThreadPanel before tearing down the
   * previous panel — continuations below compare `myToken !==
   * _threadOpenToken` to know they were superseded (msg#17058). */
  var myToken = ++_threadOpenToken;
  closeThreadPanel({ skipPushState: true });
  (globalThis as any).threadPanelParentId = parentId;
  if (!(opts && opts.skipPushState)) {
    _pushThreadUrlState(parentId);
  }

  /* Build the parent message preview from the DOM */
  var parentPreview = _buildParentPreview(parentId);

  (globalThis as any).threadPanel = document.createElement("div");
  (globalThis as any).threadPanel.className = "thread-panel";
  /* Thread panel shell only; composer DOM (textarea, attach/sketch/voice
   * buttons, send button, hidden file input) is built by renderComposer
   * below and mounted into #thread-composer-slot. Legacy IDs
   * (#thread-input, #thread-attach-btn, #thread-sketch-btn,
   * #thread-voice-btn, #thread-voice-lang-btn, #thread-file-input,
   * .thread-send-btn) are preserved by the surface="reply" DOM-builder
   * in composer.ts so voice-input.ts + existing selectors keep working. */
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
    '<div class="thread-compose-row" id="thread-composer-slot"></div>' +
    "</div>";
  /* Append as flex sibling of .main inside .container (Slack-style side-by-side) */
  var container = document.querySelector(".container");
  if (container) {
    container.appendChild((globalThis as any).threadPanel);
  } else {
    document.body.appendChild((globalThis as any).threadPanel);
  }

  await loadThreadReplies(parentId);
  /* A newer openThreadPanel started during the fetch — its
   * closeThreadPanel already ripped our panel out and built a fresh
   * one. Do not proceed to mount a composer into the new panel's
   * slot; that's the newer call's job and doing it here would stack
   * a second composer (msg#17058 bug A). */
  if (myToken !== _threadOpenToken) return;

  var composerSlot = document.getElementById("thread-composer-slot");
  /* msg#16527: clear the shared pending-attachments array IN PLACE. Do
   * NOT reassign `(globalThis as any).threadPendingAttachments` — under
   * ES modules that would orphan state.ts's module-local reference, so
   * pasted / dropped images would never reach sendThreadReply. */
  resetThreadPendingAttachments();
  _renderThreadAttachmentTray();

  if (composerSlot) {
    /* Belt-and-suspenders: if anything ever leaks DOM into this slot
     * (e.g. a stale composer from an earlier race), wipe it before the
     * new mount so we never end up with stacked inputs (msg#17058). */
    composerSlot.innerHTML = "";
    _threadComposer = renderComposer(composerSlot as HTMLElement, {
      surface: "reply",
      placeholder: "Reply in thread\u2026",
      stageFiles: function (files) {
        return _stageThreadFiles(files);
      },
      onSketchOpen: function () {
        /* openSketch() sends to currentChannel; we flag _threadSketchActive
         * so the sketch-submit path knows to post as a thread-reply. */
        (globalThis as any)._threadSketchActive = true;
      },
      features: {
        mention: true,
        paste: true,
        dragDrop: false /* thread panel had no drop handler pre-SSoT; preserve current UX */,
        attach: true,
        camera: false /* Reply composer never had a camera button */,
        sketch: true,
        voice: true,
        sendButton: true,
        cmdEnterSubmit: true,
        shiftEnterNewline: true,
        autoResize: true,
        tabAwareFocus: false,
        /* voice-input.ts's global chord handler bails when focus is
         * inside .thread-panel, so the composer owns Alt/Ctrl+Enter
         * here. */
        localVoiceChord: true,
      },
      maxResizePx: 120,
      onSubmit: function () {
        sendThreadReply();
      },
    });

    /* Add legacy class names additively so existing .thread-* CSS still
     * applies. */
    var ta = _threadComposer.input;
    ta.classList.add("thread-textarea");
    var sendBtn = composerSlot.querySelector(".composer-btn-send");
    if (sendBtn) sendBtn.classList.add("thread-send-btn");

    /* msg#16324: hydrate any persisted thread-reply draft so the user's
     * in-progress text survives page reload / deploy. Target key is
     * "msg<parentId>" per spec (orochi.draft.thread.msg12345). */
    try {
      var _saved = loadDraft("thread", _threadDraftTarget(parentId));
      if (_saved && !ta.value) {
        ta.value = _saved;
        /* Match the auto-resize behavior used by the composer. */
        ta.style.height = "auto";
        ta.style.height = Math.min(ta.scrollHeight, 120) + "px";
      }
    } catch (_) {}
    try { ta.focus(); } catch (_) {}
    /* Place cursor at end of restored draft. */
    try {
      var _len = ta.value ? ta.value.length : 0;
      ta.setSelectionRange(_len, _len);
    } catch (_) {}

    /* Persist every keystroke (debounced at 300ms via draft-store). */
    ta.addEventListener("input", function () {
      try {
        _debounceSave(
          "thread",
          _threadDraftTarget((globalThis as any).threadPanelParentId),
          this.value,
        );
      } catch (_) {}
    });

    /* Thread-specific voice language button: sync label with the Chat
     * voice-lang button (voice-input.ts manages the shared state). This
     * is the one bit of wiring the generic composer can't own because
     * the language button is thread-only chrome. */
    var voiceLangBtn = document.getElementById("thread-voice-lang-btn");
    if (voiceLangBtn) {
      var mainLangBtn = document.getElementById("msg-voice-lang");
      if (mainLangBtn) voiceLangBtn.textContent = mainLangBtn.textContent;
      voiceLangBtn.addEventListener("click", function () {
        if (typeof (window as any).cycleVoiceLang === "function") {
          (window as any).cycleVoiceLang();
          if (mainLangBtn) voiceLangBtn.textContent = mainLangBtn.textContent;
        }
      });
    }
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
    /* If a newer openThreadPanel ran during the fetch, our `container`
     * was detached when closeThreadPanel removed the old panel. Writing
     * replies into a detached node renders nothing (msg#17058 bug B).
     * Re-query; if the live panel is for a *different* parent, bail
     * and let its own loadThreadReplies fill it. */
    if (!container.isConnected) {
      container = document.getElementById("thread-replies");
      if (
        !container ||
        Number((globalThis as any).threadPanelParentId) !== Number(parentId)
      ) {
        return;
      }
    }
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
  /* msg#16527: read from the shared SSoT accessor, not
   * `(globalThis as any).threadPendingAttachments`. The globalThis
   * mirror falls out of sync across ES-module boundaries every time
   * panel.ts reassigned it, so pasted / dropped images sat in
   * state.ts's local array but were missed by the send payload. */
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
  /* Clear thread attachment tray — in-place mutate so the state.ts
   * module-local reference stays authoritative. */
  resetThreadPendingAttachments();
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
    /* msg#16324: drop the per-thread draft now that the reply landed. */
    try {
      clearDraft(
        "thread",
        _threadDraftTarget((globalThis as any).threadPanelParentId),
      );
    } catch (_) {}
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
