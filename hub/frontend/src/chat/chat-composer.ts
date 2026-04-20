// @ts-nocheck
import { lastActiveChannel } from "../app/state";
import { sendOrochiMessage, userName } from "../app/utils";
import { ws, wsConnected } from "../app/websocket";
import { _renderMermaidIn } from "./chat-attachments";
import { clearPendingAttachments, getPendingAttachments } from "../upload";

export function updateChannelSelect() {
  /* Channel select removed -- using sidebar selection instead */
}

export function sendMessage() {
  var input = document.getElementById("msg-input");
  /* In multi-select mode (globalThis as any).currentChannel is null; fall back to lastActiveChannel
   * so the message goes to the last focused channel (#9694). */
  var channel =
    (globalThis as any).currentChannel ||
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
  /* Clear the per-channel draft now that the message has been sent. */
  try {
    sessionStorage.removeItem(
      "orochi-draft-" + ((globalThis as any).currentChannel || "__default__"),
    );
  } catch (_) {}
  /* Hands-free voice dictation: if the mic is currently listening, the
   * next recognition.result event would re-render the entire cumulative
   * session transcript on top of the now-empty input. Tell voice-input.js
   * to reset its baseText snapshot AND restart the recognition session
   * so the input stays clean. ywatanabe wants to leave the mic on for
   * continuous dictation across multiple sends (msg#6500 / msg#6504). */
  if (typeof window.voiceInputResetAfterSend === "function") {
    try {
      window.voiceInputResetAfterSend();
    } catch (_) {}
  }
}

/* Auto-resize textarea as content grows + persist draft per channel.
 *
 * The draft is keyed by `(globalThis as any).currentChannel` so switching channels preserves
 * each channel's in-progress message. On page reload (or DOM re-render
 * accident), restoreDraftForCurrentChannel() puts the text back. We use
 * sessionStorage so drafts disappear when the tab closes — closer to a
 * "scratchpad" semantic than localStorage's "permanent" feel.
 */
export function _draftKey() {
  try {
    return "orochi-draft-" + ((globalThis as any).currentChannel || "__default__");
  } catch (_) {
    return "orochi-draft-__default__";
  }
}
export function _saveDraft(value) {
  try {
    if (value && value.length > 0) {
      sessionStorage.setItem(_draftKey(), value);
    } else {
      sessionStorage.removeItem(_draftKey());
    }
  } catch (_) {
    /* sessionStorage may be unavailable in private mode */
  }
}
export function restoreDraftForCurrentChannel() {
  try {
    var input = document.getElementById("msg-input");
    if (!input) return;
    var saved = sessionStorage.getItem(_draftKey());
    if (saved && !input.value) {
      input.value = saved;
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 200) + "px";
    }
  } catch (_) {}
}
window.restoreDraftForCurrentChannel = restoreDraftForCurrentChannel;
document.getElementById("msg-input").addEventListener("input", function () {
  this.style.height = "auto";
  this.style.height = Math.min(this.scrollHeight, 200) + "px";
  _saveDraft(this.value);
});
restoreDraftForCurrentChannel();

/* Diagnostic blur logger for todo#225 — captures every blur event on
 * #msg-input with timestamp, relatedTarget, and a trimmed stack trace,
 * stored in sessionStorage so a user (or mamba-verifier-mba via
 * playwright) can inspect the last N events with
 *   JSON.parse(sessionStorage.getItem("orochi-blurlog") || "[]")
 * after reproducing the bug. Async-safe (uses requestAnimationFrame to
 * also catch deferred re-blurs that happen after a synchronous
 * focus-restore). Capacity-bounded at 50 entries so it never grows
 * unbounded. Strictly diagnostic — no UI side-effect. */
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
    /* Also check after one frame in case something defers focus theft */
    requestAnimationFrame(function () {
      if (document.activeElement !== input) {
        _logBlur("post-rAF-still-blurred", e);
      }
    });
  });
  /* Also expose a one-shot getter for convenience */
  window.getBlurLog = function () {
    try {
      return JSON.parse(sessionStorage.getItem("orochi-blurlog") || "[]");
    } catch (_) {
      return [];
    }
  };
})();

/* Focus-theft guard removed: the capture-phase mousedown delegate that
 * kept #msg-input focused when the user clicked feed buttons/links felt
 * too aggressive. Browser default focus behavior is now in effect —
 * clicks on feed elements shift focus naturally. The save→render→
 * restore pattern in the render functions still preserves mid-typing
 * state across polling re-renders; it just no longer fights user
 * clicks. */

/* Show more / Show less toggle for long messages.
 * Uses delegated click on document to handle dynamically inserted buttons.
 * Replaces the previous fragile inline onclick with arguments.callee. */
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
    /* Render mermaid diagrams that became visible in the expanded section */
    _renderMermaidIn(fullEl);
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

/* Defensive blur watchdog (todo#225 second-order regression).
 * msg#6692: ywatanabe says focus drops *after an idle period when a
 * delayed post arrives* — i.e. NOT a click event, so the mousedown
 * delegate above can't catch it. Some async setInterval / WS-driven
 * DOM mutation is firing focus() on something else, or the textarea
 * itself is being briefly unmounted by a re-render. Rather than chase
 * every async path, install a one-shot watchdog: if #msg-input loses
 * focus AND nothing else useful (form control / link the user clicked
 * intentionally) took focus within the next paint frame, snap focus
 * straight back. The selection range is restored too so the cursor
 * lands where the user left it. We only re-focus when the textarea
 * still has user-typed content AND the focus shifted to <body> /
 * <button> / <a> — the "implicit blur" pattern — so we never fight
 * an intentional click into another textarea / input / select. */
(function () {
  var msgInput = document.getElementById("msg-input");
  if (!msgInput) return;
  msgInput.addEventListener("blur", function (e) {
    if (window.__voiceInputAllowBlur) return;
    var savedStart = msgInput.selectionStart || 0;
    var savedEnd = msgInput.selectionEnd || 0;
    var rt = e && e.relatedTarget;
    /* If the user clicked into another form control on purpose, leave
     * the focus where they put it. */
    if (rt && rt.tagName) {
      var tn = rt.tagName.toUpperCase();
      if (tn === "TEXTAREA" || tn === "INPUT" || tn === "SELECT") return;
      if (rt.isContentEditable) return;
    }
    requestAnimationFrame(function () {
      var still = document.activeElement;
      if (still === msgInput) return;
      /* Don't fight a real focus into another control. */
      if (still && still.tagName) {
        var stn = still.tagName.toUpperCase();
        if (stn === "TEXTAREA" || stn === "INPUT" || stn === "SELECT") return;
        if (still.isContentEditable) return;
      }
      /* todo#315: don't snap focus back if the user is actively
       * selecting text inside the message feed — refocusing would
       * collapse the selection and make copy impossible. */
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
  /* Ctrl+U / Cmd+U → trigger file upload picker (msg#9877) */
  var isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
  if ((isMac ? e.metaKey : e.ctrlKey) && e.key === "u") {
    e.preventDefault();
    var fi = document.getElementById("file-input");
    if (fi) fi.click();
    return;
  }
  if (e.key === "Enter") {
    var dd = document.getElementById("mention-dropdown");
    if (dd && dd.classList.contains("visible")) return;
    /* todo#332 v2: Alt+Enter is reserved for voice toggle (see voice-input.js).
     * Shift+Enter remains the newline shortcut. Plain Enter sends. */
    if (e.shiftKey) return;
    if (e.altKey) {
      /* Voice toggle handled by voice-input.js global handler — just prevent default */
      e.preventDefault();
      return;
    }
    e.preventDefault();
    sendMessage();
  }
});
