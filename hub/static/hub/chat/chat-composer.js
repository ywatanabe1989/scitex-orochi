/* chat-composer.js — mirror of chat-composer.ts.
 *
 * Since the composer SSoT unification (feat/composer-ssot-unification)
 * the core keydown / send / autoresize / mention wiring is owned by
 * composer.js::renderComposer(). Chat-specific extras (draft-store
 * hydration, blur watchdog, diagnostic blur logger, show-more toggle,
 * mermaid raw-script toggle) remain in this file because they are not
 * cross-surface concerns. */
/* globals: ws, wsConnected, sendOrochiMessage, userName, currentChannel,
   lastActiveChannel, getPendingAttachments, clearPendingAttachments,
   stageFiles, renderComposer, activeTab, _renderMermaidIn */

function updateChannelSelect() {
  /* Channel select removed -- using sidebar selection instead */
}

function sendMessage() {
  var input = document.getElementById("msg-input");
  /* In multi-select mode currentChannel is null; fall back to lastActiveChannel
   * so the message goes to the last focused channel (#9694). */
  var channel =
    currentChannel ||
    (typeof lastActiveChannel !== "undefined" && lastActiveChannel) ||
    "#general";
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
  /* Clear the per-channel draft now that the message has been sent
   * (msg#16324: localStorage-backed draft-store replaces the old
   * sessionStorage scratch). */
  try {
    if (window.orochiDraftStore) {
      window.orochiDraftStore.clearDraft(
        "chat",
        currentChannel || "__default__",
      );
    }
  } catch (_) {}
  /* Hands-free voice dictation: reset voice input baseText + restart
   * session so the textarea stays clean across sends. */
  if (typeof window.voiceInputResetAfterSend === "function") {
    try {
      window.voiceInputResetAfterSend();
    } catch (_) {}
  }
}

function _draftTarget() {
  try {
    return currentChannel || "__default__";
  } catch (_) {
    return "__default__";
  }
}
function restoreDraftForCurrentChannel() {
  try {
    var input = document.getElementById("msg-input");
    if (!input) return;
    if (input.value) return; /* don't clobber live text */
    var ds = window.orochiDraftStore;
    if (!ds) return;
    var saved = ds.loadDraft("chat", _draftTarget());
    if (saved) {
      input.value = saved;
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 200) + "px";
      try {
        input.setSelectionRange(saved.length, saved.length);
      } catch (_) {}
    }
  } catch (_) {}
}
window.restoreDraftForCurrentChannel = restoreDraftForCurrentChannel;

/* SSoT composer — adopts the existing dashboard.html .input-bar DOM. All
 * per-module wiring (paste / drop / attach / camera / sketch / voice) is
 * owned by upload.js / webcam.js / sketch.js / voice-input.js; the
 * composer only provides keyboard shortcuts + send dispatch here. */
(function () {
  var inputBar = document.querySelector(".input-bar");
  var msgInput = document.getElementById("msg-input");
  if (!inputBar || !msgInput || typeof renderComposer !== "function") return;
  inputBar.setAttribute("data-composer-surface", "chat");
  renderComposer(inputBar, {
    surface: "chat",
    adoptRoot: inputBar,
    adoptSelectors: {
      input: "#msg-input",
      sendBtn: "#msg-send",
    },
    stageFiles: function (files) {
      if (typeof stageFiles === "function") return stageFiles(files);
    },
    features: {
      mention: false /* mention.js already attaches handlers to #msg-input */,
      paste: false /* upload.js owns msg-input paste */,
      dragDrop: false /* upload.js owns msg-input drop */,
      attach: false /* upload.js owns #msg-attach click + #file-input change */,
      camera: false /* webcam.js owns #msg-webcam click */,
      sketch: false /* sketch.js owns #msg-sketch click */,
      voice: false /* voice-input.js owns #msg-voice click */,
      sendButton: true,
      cmdEnterSubmit: true,
      shiftEnterNewline: true,
      autoResize: true,
      tabAwareFocus: true,
      localVoiceChord: false,
    },
    maxResizePx: 200,
    onSubmit: function () {
      sendMessage();
    },
  });
})();

/* Persist draft on every input, debounced at 300ms via draft-store. */
document.getElementById("msg-input").addEventListener("input", function () {
  try {
    if (window.orochiDraftStore) {
      window.orochiDraftStore._debounceSave("chat", _draftTarget(), this.value);
    }
  } catch (_) {}
});
restoreDraftForCurrentChannel();

/* Diagnostic blur logger for todo#225. */
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
          ? (rt.tagName || "?") +
            "#" +
            (rt.id || "") +
            "." +
            (rt.className || "")
          : null,
        activeAfter: document.activeElement
          ? document.activeElement.tagName +
            "#" +
            (document.activeElement.id || "")
          : null,
        stack: new Error().stack
          ? new Error().stack.split("\n").slice(2, 8).join(" | ")
          : null,
      });
      while (arr.length > 50) arr.shift();
      sessionStorage.setItem("orochi-blurlog", JSON.stringify(arr));
    } catch (_) {}
  }
  input.addEventListener("blur", function (e) {
    _logBlur("sync-blur", e);
    requestAnimationFrame(function () {
      if (document.activeElement !== input) {
        _logBlur("post-rAF-still-blurred", e);
      }
    });
  });
  window.getBlurLog = function () {
    try {
      return JSON.parse(sessionStorage.getItem("orochi-blurlog") || "[]");
    } catch (_) {
      return [];
    }
  };
})();

/* Show more / Show less toggle for long messages. */
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
    if (typeof _renderMermaidIn === "function") _renderMermaidIn(fullEl);
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

/* Defensive blur watchdog (todo#225 second-order regression). */
(function () {
  var msgInput = document.getElementById("msg-input");
  if (!msgInput) return;
  msgInput.addEventListener("blur", function (e) {
    if (window.__voiceInputAllowBlur) return;
    var _activeTab =
      typeof window !== "undefined" && typeof window.activeTab === "string"
        ? window.activeTab
        : typeof activeTab === "string"
          ? activeTab
          : "";
    if (_activeTab !== "chat") return;
    var savedStart = msgInput.selectionStart || 0;
    var savedEnd = msgInput.selectionEnd || 0;
    var rt = e && e.relatedTarget;
    if (rt && rt.tagName) {
      var tn = rt.tagName.toUpperCase();
      if (tn === "TEXTAREA" || tn === "INPUT" || tn === "SELECT") return;
      if (rt.isContentEditable) return;
    }
    requestAnimationFrame(function () {
      var still = document.activeElement;
      if (still === msgInput) return;
      if (still && still.tagName) {
        var stn = still.tagName.toUpperCase();
        if (stn === "TEXTAREA" || stn === "INPUT" || stn === "SELECT") return;
        if (still.isContentEditable) return;
      }
      try {
        var sel = window.getSelection && window.getSelection();
        if (sel && sel.toString().length > 0) {
          var anchor = sel.anchorNode;
          if (anchor && anchor.nodeType === 3) anchor = anchor.parentElement;
          if (
            anchor &&
            anchor.closest &&
            anchor.closest("#messages, .msg, .thread-panel")
          ) {
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
