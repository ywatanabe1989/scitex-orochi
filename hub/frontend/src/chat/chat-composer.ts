// @ts-nocheck
import { lastActiveChannel } from "../app/state";
import { sendOrochiMessage, userName, apiUrl } from "../app/utils";
import { ws, wsConnected } from "../app/websocket";
import { _renderMermaidIn } from "./chat-attachments";
import {
  clearPendingAttachments,
  getPendingAttachments,
  stageFiles,
} from "../upload";
import { activeTab } from "../tabs";
import {
  _debounceSave,
  clearDraft,
  loadDraft,
} from "../composer/draft-store";
import { renderComposer } from "../composer/composer";

export function updateChannelSelect() {
  /* Channel select removed -- using sidebar selection instead */
}

/* sendMessage is invoked by renderComposer's onSubmit as well as by
 * legacy entry points (mobile Safari send-button path etc.). Pulls
 * attachments from upload.ts's pending tray (the Chat surface owns
 * pendingAttachments — the Overview popup and Reply composer have
 * their own per-surface stores so this module is unchanged by the
 * unification). */
/* #245/#246/#247/#248: slash-command registry.
 * Each entry: { args, summary } — consumed by /help to list commands.
 * Handlers live in _handleSlashCommand() below. */
var SLASH_COMMANDS = [
  { cmd: "/mute",       args: "[#channel]",                      summary: "Mute current or named channel" },
  { cmd: "/unmute",     args: "[#channel]",                      summary: "Unmute current or named channel" },
  { cmd: "/leave",      args: "[#channel]",                      summary: "Unsubscribe from current or named channel" },
  { cmd: "/topic",      args: "<text>",                          summary: "Set the current channel description" },
  { cmd: "/remind",     args: "<me|#ch|@agent> in <N>m|h <msg>", summary: "Schedule a reminder message" },
  { cmd: "/help",       args: "",                                summary: "List slash commands and keyboard shortcuts" },
  { cmd: "/shortcuts",  args: "",                                summary: "Alias for /help" },
];

/* Show a mini-toast; delegates to window._showMiniToast if available. */
function _toast(text: string, kind?: string) {
  if (typeof (window as any)._showMiniToast === "function") {
    (window as any)._showMiniToast(text, kind);
  }
}

/* #245/#246/#247/#248: slash-command router — intercepts text beginning with
 * "/" before the WS/REST send path. Returns true if a command matched
 * (caller clears the input and returns without sending). */
function _handleSlashCommand(text: string, channel: string): boolean {
  var parts = text.trim().split(/\s+/);
  var cmd = parts[0].toLowerCase();

  /* ── /mute [#channel]  (#245) ─────────────────────────────────────── */
  if (cmd === "/mute" || cmd === "/unmute") {
    var target = parts[1] || "";
    if (target && !target.startsWith("#")) target = "#" + target;
    if (!target) target = channel;
    if (!target) return true;
    var mute = cmd === "/mute";
    if (typeof (window as any)._setChannelPref === "function") {
      (window as any)._setChannelPref(target, { is_muted: mute });
    }
    _toast((mute ? "Muted " : "Unmuted ") + target, mute ? "warn" : "success");
    return true;
  }

  /* ── /leave [#channel]  (#248) ────────────────────────────────────── */
  if (cmd === "/leave") {
    var leaveTarget = parts[1] || "";
    if (leaveTarget && !leaveTarget.startsWith("#")) leaveTarget = "#" + leaveTarget;
    if (!leaveTarget) leaveTarget = channel;
    if (!leaveTarget) return true;
    /* Guard: don't allow leaving DMs or #general */
    if (leaveTarget === "#general" || leaveTarget.startsWith("dm:")) {
      _toast("Cannot leave " + leaveTarget, "warn");
      return true;
    }
    fetch(apiUrl("/api/channel-members/"), {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channel: leaveTarget, username: userName }),
    })
      .then(function (r) {
        _toast(r.ok ? "Left " + leaveTarget : "Error leaving " + leaveTarget,
               r.ok ? "success" : "warn");
        /* Trigger sidebar refresh so the channel disappears */
        if (typeof (window as any).fetchStats === "function") {
          (window as any).fetchStats();
        }
      })
      .catch(function () { _toast("Error leaving " + leaveTarget, "warn"); });
    return true;
  }

  /* ── /topic <text>  (#246) ────────────────────────────────────────── */
  if (cmd === "/topic") {
    var description = parts.slice(1).join(" ").trim();
    fetch(apiUrl("/api/channels/"), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: channel, description: description }),
    })
      .then(function (r) {
        _toast(r.ok ? "Topic set" : "Error setting topic", r.ok ? "success" : "warn");
      })
      .catch(function () { _toast("Error setting topic", "warn"); });
    return true;
  }

  /* ── /help or /shortcuts  (#247) ──────────────────────────────────── */
  if (cmd === "/help" || cmd === "/shortcuts") {
    var lines = ["Slash commands:"];
    SLASH_COMMANDS.forEach(function (c) {
      lines.push("  " + c.cmd + (c.args ? " " + c.args : "") + " — " + c.summary);
    });
    lines.push("");
    lines.push("Keyboard shortcuts:");
    lines.push("  Ctrl+K — search / jump to channel");
    lines.push("  Alt+Enter / Ctrl+M — toggle voice input");
    lines.push("  Shift+Enter — newline in composer");
    lines.push("  Ctrl+U — upload file");
    var helpText = lines.join("\n");
    /* Post as an ephemeral local message if appendMessage is available,
     * otherwise fall back to an alert. */
    if (typeof (window as any).appendMessage === "function") {
      (window as any).appendMessage({
        sender: "orochi",
        content: helpText,
        channel: channel,
        ts: new Date().toISOString(),
        local: true,
      });
    } else {
      alert(helpText);
    }
    return true;
  }

  /* ── /remind <target> in <N>m|h|d <message>  (#244) ──────────────── */
  if (cmd === "/remind") {
    /* Grammar: /remind <target> in <N><unit> <body>
     *            target = me | #channel | @agent (default: me)
     *            N      = positive integer
     *            unit   = m(in) | h(our) | d(ay)
     *            body   = remainder of the string
     * Examples:
     *   /remind me in 30m to check the dispatch queue
     *   /remind #proj-foo in 2h about standup
     *   /remind @mgr-todo in 1h about stuck thread  */
    var remindArgs = parts.slice(1); /* everything after /remind */
    var remindTarget = "me";
    var timeIdx = 0; /* index in remindArgs where "in" appears */
    /* Optional first word is target if it starts with #, @, or is "me" */
    if (remindArgs.length > 0) {
      var first = remindArgs[0].toLowerCase();
      if (first === "me" || first.startsWith("#") || first.startsWith("@")) {
        remindTarget = remindArgs[0];
        remindArgs = remindArgs.slice(1);
      }
    }
    /* Find "in" keyword */
    var inIdx = remindArgs.map(function (w) { return w.toLowerCase(); }).indexOf("in");
    if (inIdx === -1) {
      _toast("/remind: use 'in <N>m|h|d' for time", "warn");
      return true;
    }
    var quantStr = remindArgs[inIdx + 1] || "";
    var quantMatch = quantStr.match(/^(\d+)(m(?:in)?|h(?:r|our)?|d(?:ay)?)$/i);
    if (!quantMatch) {
      _toast("/remind: expected <N>m|h|d, got '" + quantStr + "'", "warn");
      return true;
    }
    var qty = parseInt(quantMatch[1], 10);
    var unit = quantMatch[2][0].toLowerCase(); /* m | h | d */
    var delayMs = qty * (unit === "m" ? 60 : unit === "h" ? 3600 : 86400) * 1000;
    var fireAt = new Date(Date.now() + delayMs).toISOString();
    var bodyWords = remindArgs.slice(inIdx + 2);
    /* Strip leading "to" / "about" / "that" filler words */
    if (bodyWords.length > 0 && /^(to|about|that|for)$/i.test(bodyWords[0])) {
      bodyWords = bodyWords.slice(1);
    }
    var remindBody = bodyWords.join(" ").trim() || "(no message)";
    /* Resolve destination channel */
    var remindChannel = channel || "#general";
    var remindAgent = userName || "ywatanabe";
    if (remindTarget !== "me") {
      if (remindTarget.startsWith("#")) {
        remindChannel = remindTarget;
      } else if (remindTarget.startsWith("@")) {
        remindAgent = remindTarget.slice(1);
      }
    }
    /* POST to /api/scheduled/ */
    var orochiToken = (window as any).__orochiToken || "";
    fetch(apiUrl("/api/scheduled/"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token: orochiToken,
        agent: remindAgent,
        task: remindBody,
        channel: remindChannel,
        run_at: fireAt,
        created_by: userName || "",
      }),
    })
      .then(function (r) {
        if (r.ok) {
          _toast("Reminder set in " + qty + (unit === "m" ? "m" : unit === "h" ? "h" : "d"), "success");
        } else {
          r.json().then(function (e) { _toast("Reminder error: " + (e.error || r.status), "warn"); });
        }
      })
      .catch(function () { _toast("Reminder request failed", "warn"); });
    return true;
  }

  return false; /* unknown command — let it post as a normal message */
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

  /* #245: slash commands — handle before sending. Clear input + return. */
  if (text.startsWith("/") && _handleSlashCommand(text, channel)) {
    input.value = "";
    input.style.height = "auto";
    return;
  }

  /* Pull any attachments the user staged via paste/drop/picker before
   * hitting Send. Attachments alone (empty text) are a valid message. */
  var attachments =
    typeof getPendingAttachments === "function" ? getPendingAttachments() : [];
  if (!text && attachments.length === 0) return;

  var payload = { channel: channel, content: text };
  if (attachments.length > 0) payload.attachments = attachments;

  /* Prefer WebSocket send when connected (instant echo), fall back to REST */
  /* #239: set flag so chat-render scrolls when the WS echo renders the new
   * message, even if voice recording is active at that moment. */
  window._scrollAfterNextMessage = true;
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
    clearDraft(
      "chat",
      (globalThis as any).currentChannel || "__default__",
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

/* Drafts are stored in localStorage (not sessionStorage anymore —
 * msg#16324 ywatanabe: deploys / Cmd-R / reloads were clobbering
 * in-progress messages). The draft-store module handles the
 * per-(surface,target) keying, 24h stale-cutoff, and private-mode
 * failure tolerance; this module just calls into it. Cursor is
 * placed at end on restore so the user can keep typing without
 * fighting caret position.
 */
export function _draftTarget() {
  try {
    return (globalThis as any).currentChannel || "__default__";
  } catch (_) {
    return "__default__";
  }
}
export function restoreDraftForCurrentChannel() {
  try {
    var input = document.getElementById("msg-input");
    if (!input) return;
    /* Don't clobber text the user is actively typing right now. */
    if (input.value) return;
    var saved = loadDraft("chat", _draftTarget());
    if (saved) {
      input.value = saved;
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 200) + "px";
      /* Place cursor at end (spec: msg#16324). */
      try {
        var end = saved.length;
        input.setSelectionRange(end, end);
      } catch (_) {}
      /* If Chat is the active tab, blur-then-refocus so the caret
       * visibly lands at the restored position. */
      if (activeTab === "chat" && document.activeElement === input) {
        try {
          input.blur();
          input.focus();
          input.setSelectionRange(saved.length, saved.length);
        } catch (_) {}
      }
    }
  } catch (_) {}
}
window.restoreDraftForCurrentChannel = restoreDraftForCurrentChannel;

/* SSoT composer — adopts the existing dashboard.html .input-bar DOM by
 * selector rather than re-rendering so every legacy ID (#msg-input,
 * #msg-send, #msg-attach, #msg-webcam, #msg-sketch, #msg-voice,
 * #msg-voice-lang, #file-input, #pending-attachments) remains in place
 * for voice-input.ts / upload.ts / webcam.ts / sketch.ts / etc.
 *
 * Several Chat features DON'T come from renderComposer because upload.ts
 * already binds them globally on module load (Ctrl+U file picker,
 * msg-input drop, paste handler), webcam.ts owns the camera button,
 * sketch.ts owns the sketch button, and voice-input.ts owns the voice
 * chord and button. The composer owns:
 *   - #msg-send click  → sendMessage via onSubmit
 *   - plain-Enter / Shift+Enter semantics
 *   - auto-resize up to 200px
 *   - tab-aware focus hint
 * The parity matrix in the PR body documents this split. */
var _chatComposer = (function () {
  var inputBar = document.querySelector(".input-bar");
  var msgInput = document.getElementById("msg-input");
  if (!inputBar || !msgInput) return null;
  inputBar.setAttribute("data-composer-surface", "chat");
  return renderComposer(inputBar as HTMLElement, {
    surface: "chat",
    adoptRoot: inputBar as HTMLElement,
    adoptSelectors: {
      input: "#msg-input",
      sendBtn: "#msg-send",
    },
    stageFiles: function (files) {
      return stageFiles(files);
    },
    features: {
      mention: false /* mention.ts already calls initMentionAutocomplete(#msg-input) */,
      paste: false /* upload.ts owns msg-input paste */,
      dragDrop: false /* upload.ts owns msg-input drop */,
      attach: false /* upload.ts owns #msg-attach click + #file-input change */,
      camera: false /* webcam.ts owns #msg-webcam click */,
      sketch: false /* sketch.ts owns #msg-sketch click */,
      voice: false /* voice-input.ts owns #msg-voice click */,
      sendButton: true,
      cmdEnterSubmit: true,
      shiftEnterNewline: true,
      autoResize: true,
      tabAwareFocus: true,
      /* voice-input.ts installs a global capture-phase Alt/Ctrl+Enter
       * handler that fires for the Chat surface; the composer must
       * not also handle it or the mic toggles twice. */
      localVoiceChord: false,
    },
    maxResizePx: 200,
    onSubmit: function (_payload) {
      sendMessage();
    },
  });
})();

/* Persist draft on every input, debounced at 300ms via draft-store.
 * Kept as a separate listener from the composer's internal autoresize
 * because draft persistence is Chat-specific on this codepath (the
 * Overview popup + thread reply own their own debounced-save wiring
 * in their respective modules). */
document.getElementById("msg-input").addEventListener("input", function () {
  _debounceSave("chat", _draftTarget(), this.value);
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
    /* msg#16116 Item 2: never re-focus msg-input from a non-Chat tab.
     * When the user is on Overview/TODO/etc the input bar is display:none
     * and the watchdog's rAF refocus either silently no-ops (browsers
     * refuse to focus display:none elements) or — under race conditions
     * with rapid tab switches — can briefly park focus on msg-input and
     * cascade into a Chat-tab flip via downstream focus-in handlers.
     * Guard: if Chat isn't the active tab, leave the blur where it is. */
    if (activeTab !== "chat") return;
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
