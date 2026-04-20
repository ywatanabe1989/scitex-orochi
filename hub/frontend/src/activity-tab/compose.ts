// @ts-nocheck
import { _activityChannelRequest, _invalidateTopoPerms } from "./data";
import { _showMiniToast } from "../app/agent-actions";
import { _channelPrefs } from "../app/members";
import { fetchAgents } from "../app/sidebar-agents";
import { setCurrentChannel } from "../app/state";
import { escapeHtml, sendOrochiMessage, userName } from "../app/utils";
import { ws, wsConnected } from "../app/websocket";
import { loadChannelHistory } from "../chat/chat-history";

/* activity-tab/compose.js — group compose modal (multi-select post)
 * + inline channel compose popup + drag-ghost helper + subscribe toast. */


/* ─── Multi-select group compose modal ───────────────────────────
 * Opened from the floating action bar when ≥2 agents are selected.
 * Two posting modes:
 *   mention  → a single post in a chosen channel with @agent1 @agent2
 *              prepended to the text (needs a channel selector).
 *   group-dm → create/ensure a DM channel named
 *              "dm:group:<sorted,comma-joined,names>", subscribe each
 *              selected agent as read-write, then post the text.
 * Modal Escape closes it; we use a capture-phase listener that stops
 * propagation so the topology Escape = zoom-back handler doesn't also
 * fire while the modal is open. */
export var _topoComposeEl = null;
export var _topoComposeEscapeHandler = null;

export function _closeTopoGroupCompose() {
  if (_topoComposeEl && _topoComposeEl.parentNode) {
    _topoComposeEl.parentNode.removeChild(_topoComposeEl);
  }
  _topoComposeEl = null;
  if (_topoComposeEscapeHandler) {
    document.removeEventListener("keydown", _topoComposeEscapeHandler, true);
    _topoComposeEscapeHandler = null;
  }
}

export function _openTopoGroupCompose(agents) {
  if (!Array.isArray(agents) || agents.length < 2) return;
  _closeTopoGroupCompose();
  /* Channel options come from the global _channelPrefs map (app.js).
   * Skip dm: entries; they aren't useful as mention destinations. */
  var prefs = (typeof _channelPrefs !== "undefined" && _channelPrefs) || {};
  var chOpts = Object.keys(prefs)
    .filter(function (n) {
      return n && n.indexOf("dm:") !== 0;
    })
    .sort()
    .map(function (n) {
      return (
        '<option value="' + escapeHtml(n) + '">' + escapeHtml(n) + "</option>"
      );
    })
    .join("");
  var chips = agents
    .map(function (n) {
      return '<span class="topo-compose-chip">' + escapeHtml(n) + "</span>";
    })
    .join("");
  var overlay = document.createElement("div");
  overlay.className = "topo-compose-overlay";
  overlay.innerHTML =
    '<div class="topo-compose-modal" role="dialog" aria-modal="true">' +
    '<div class="topo-compose-header">' +
    '<span class="topo-compose-title">Post to ' +
    agents.length +
    " selected agents</span>" +
    '<button type="button" class="topo-compose-close" data-topo-compose="cancel" title="Close (Esc)">×</button>' +
    "</div>" +
    '<div class="topo-compose-body">' +
    '<div class="topo-compose-targets">' +
    chips +
    "</div>" +
    '<label class="topo-compose-label">Message</label>' +
    '<textarea class="topo-compose-text" rows="4" placeholder="Type your message…"></textarea>' +
    '<fieldset class="topo-compose-mode">' +
    '<legend class="topo-compose-label">Delivery</legend>' +
    '<label class="topo-compose-radio"><input type="radio" name="topo-compose-mode" value="mention"> mention in channel</label>' +
    '<label class="topo-compose-radio"><input type="radio" name="topo-compose-mode" value="group-dm" checked> group DM</label>' +
    "</fieldset>" +
    '<div class="topo-compose-channel" style="display:none">' +
    '<label class="topo-compose-label">Channel</label>' +
    '<select class="topo-compose-channel-select">' +
    chOpts +
    "</select>" +
    "</div>" +
    "</div>" +
    '<div class="topo-compose-footer">' +
    '<button type="button" class="topo-compose-btn" data-topo-compose="cancel">Cancel</button>' +
    '<button type="button" class="topo-compose-btn topo-compose-btn-primary" data-topo-compose="post">Post</button>' +
    "</div></div>";
  document.body.appendChild(overlay);
  _topoComposeEl = overlay;

  var textEl = overlay.querySelector(".topo-compose-text");
  var modeRadios = overlay.querySelectorAll('input[name="topo-compose-mode"]');
  var chBox = overlay.querySelector(".topo-compose-channel");
  var chSelect = overlay.querySelector(".topo-compose-channel-select");
  function _currentMode() {
    for (var i = 0; i < modeRadios.length; i++) {
      if (modeRadios[i].checked) return modeRadios[i].value;
    }
    return "group-dm";
  }
  function _syncModeUI() {
    chBox.style.display = _currentMode() === "mention" ? "" : "none";
  }
  modeRadios.forEach(function (r) {
    r.addEventListener("change", _syncModeUI);
  });
  _syncModeUI();
  setTimeout(function () {
    if (textEl) textEl.focus();
  }, 40);

  overlay.addEventListener("click", function (ev) {
    if (ev.target === overlay) {
      _closeTopoGroupCompose();
      return;
    }
    var btn = ev.target.closest("[data-topo-compose]");
    if (!btn) return;
    var action = btn.getAttribute("data-topo-compose");
    if (action === "cancel") {
      _closeTopoGroupCompose();
      return;
    }
    if (action !== "post") return;
    var text = (textEl && textEl.value ? textEl.value : "").trim();
    if (!text) {
      if (textEl) textEl.focus();
      return;
    }
    if (_currentMode() === "mention") {
      var ch = chSelect && chSelect.value ? chSelect.value : "";
      if (!ch) {
        alert("Pick a channel to mention in.");
        return;
      }
      _submitTopoMentionPost(ch, agents, text);
      _closeTopoGroupCompose();
    } else {
      _submitTopoGroupDmPost(agents, text).catch(function (err) {
        alert("Group DM failed: " + (err && err.message ? err.message : err));
      });
    }
  });

  /* Capture-phase Escape: close the modal AND stop propagation before
   * the topology Escape-handler (which pops zoom history) sees it. */
  _topoComposeEscapeHandler = function (ev) {
    if (ev.key !== "Escape") return;
    ev.preventDefault();
    ev.stopPropagation();
    _closeTopoGroupCompose();
  };
  document.addEventListener("keydown", _topoComposeEscapeHandler, true);
}

export function _submitTopoMentionPost(channel, agents, text) {
  var mentions = agents
    .map(function (n) {
      return "@" + n;
    })
    .join(" ");
  var body = mentions + " " + text;
  if (typeof sendOrochiMessage !== "function") {
    alert("sendOrochiMessage unavailable — cannot post");
    return;
  }
  sendOrochiMessage({
    type: "message",
    sender: typeof userName !== "undefined" && userName ? userName : "human",
    payload: { channel: channel, content: body },
  });
}

export async function _submitTopoGroupDmPost(agents, text) {
  var sorted = agents.slice().sort();
  var channel = "dm:group:" + sorted.join(",");
  /* Subscribe each selected agent to the new channel (read-write).
   * The backend creates the channel on first POST and the call is
   * idempotent for already-subscribed agents. Run sequentially so
   * any failure surfaces with a clear error instead of a race. */
  for (var i = 0; i < sorted.length; i++) {
    await _activityChannelRequest("POST", sorted[i], channel);
  }
  /* Invalidate perm cache since we just mutated memberships. */
  _invalidateTopoPerms();
  if (typeof sendOrochiMessage === "function") {
    sendOrochiMessage({
      type: "message",
      sender: typeof userName !== "undefined" && userName ? userName : "human",
      payload: { channel: channel, content: text },
    });
  }
  _closeTopoGroupCompose();
  /* Refresh agents so the list view reflects the new subscriptions. */
  if (typeof fetchAgents === "function") fetchAgents();
}

/* ── Drag-to-subscribe on the topology canvas ──
 *   mousedown on .topo-agent or .topo-channel starts a drag session.
 *   After a 4px threshold a ghost <text> follows the cursor.
 *   While dragging, hovered .topo-channel / .topo-agent nodes get
 *   .topo-drop-target. Release on a valid opposite-kind node calls the
 *   subscribe endpoint with the right permission; release elsewhere
 *   cancels silently.
 *
 *   Zoom/pan gestures (_wireTopoZoomPan) guard themselves with an early
 *   return when the mousedown target is an agent/channel, so the two
 *   handlers coexist without conflict. */
var _topoDragState = null;
export function _topoClearDrop() {
  if (!_topoDragState) return;
  if (_topoDragState.lastDrop) {
    _topoDragState.lastDrop.classList.remove("topo-drop-target");
    _topoDragState.lastDrop = null;
  }
}
export function _topoCleanupDrag() {
  if (!_topoDragState) return;
  _topoClearDrop();
  if (_topoDragState.ghost && _topoDragState.ghost.parentNode) {
    _topoDragState.ghost.parentNode.removeChild(_topoDragState.ghost);
  }
  _topoDragState = null;
}
/* Inline compose popup anchored near a clicked channel node. Opens on
 * double-click channel; replaces the old window.prompt() UX
 * (ywatanabe 2026-04-19: "this is too much; just show a simple one
 * near clicked point is enough"). Minimal by default: text input +
 * send button + expand chevron. When expanded, surfaces attach /
 * camera / sketch / voice buttons that delegate to the global
 * helpers already used by the Chat compose. Drag-drop files onto the
 * popup always works (collapsed or expanded). Keyboard: Enter sends,
 * Shift+Enter = newline, Esc closes. */
export function _topoOpenChannelCompose(channel, clientX, clientY) {
  /* Kill any previous popup first. */
  var prev = document.getElementById("topo-channel-compose");
  if (prev && prev.parentNode) prev.parentNode.removeChild(prev);
  var pop = document.createElement("div");
  pop.id = "topo-channel-compose";
  pop.className = "topo-channel-compose";
  pop.setAttribute("data-channel", channel);
  pop.style.left = Math.max(8, clientX - 140) + "px";
  pop.style.top = Math.max(8, clientY + 12) + "px";
  /* Minimal popup: no header, no close button, no + button, no send
   * button. Just a textarea whose tooltip documents all the keyboard
   * shortcuts, plus a small ▾ chevron at the bottom-right corner that
   * reveals attach / camera / sketch / voice buttons. Enter sends, Esc
   * closes, outside click closes. ywatanabe 2026-04-19: "make the
   * modal minimal; no send button needed; no dm nor channel label
   * needed; no plus button needed; not x button needed; just add a
   * small chevron to the bottom to show other buttons; show tooltip
   * with keyboard shortcuts even when they are not expanded to use". */
  var tccShortcuts =
    "Enter — send\n" +
    "Shift+Enter — newline\n" +
    "Esc — close\n" +
    "Drop files to attach\n" +
    "Paste image/file to attach\n" +
    "Click ▾ for attach / camera / sketch / voice";
  pop.innerHTML =
    '<textarea class="tcc-input" data-voice-input rows="2" placeholder="message #' +
    escapeHtml(channel).replace(/^#/, "") +
    '" title="' +
    tccShortcuts.replace(/"/g, "&quot;") +
    '"></textarea>' +
    '<div class="tcc-extras" style="display:none">' +
    '<button type="button" class="tcc-x tcc-attach" title="Attach file (paste also works)">\uD83D\uDCCE</button>' +
    '<button type="button" class="tcc-x tcc-camera" title="Camera">\uD83D\uDCF7</button>' +
    '<button type="button" class="tcc-x tcc-sketch" title="Sketch">\u270F\uFE0F</button>' +
    '<button type="button" class="tcc-x tcc-voice" title="Voice input">\uD83C\uDFA4</button>' +
    "</div>" +
    '<button type="button" class="tcc-expand" title="' +
    tccShortcuts.replace(/"/g, "&quot;") +
    '" aria-label="More options">\u25BE</button>';
  document.body.appendChild(pop);
  var input = pop.querySelector(".tcc-input");
  var extras = pop.querySelector(".tcc-extras");
  var expandBtn = pop.querySelector(".tcc-expand");
  setTimeout(function () {
    if (input) input.focus();
  }, 10);

  function close() {
    if (pop.parentNode) pop.parentNode.removeChild(pop);
    document.removeEventListener("mousedown", outsideClick, true);
  }
  function outsideClick(ev) {
    if (!pop.contains(ev.target)) close();
  }
  setTimeout(function () {
    document.addEventListener("mousedown", outsideClick, true);
  }, 50);

  function send() {
    var text = (input.value || "").trim();
    if (!text) return;
    var payload = { channel: channel, content: text };
    if (
      typeof wsConnected !== "undefined" &&
      wsConnected &&
      typeof ws !== "undefined" &&
      ws &&
      ws.readyState === WebSocket.OPEN
    ) {
      ws.send(JSON.stringify({ type: "message", payload: payload }));
    } else if (typeof sendOrochiMessage === "function") {
      sendOrochiMessage({
        type: "message",
        sender:
          typeof userName !== "undefined" && userName ? userName : "human",
        payload: payload,
      });
    }
    close();
  }
  input.addEventListener("keydown", function (ev) {
    /* Voice-toggle shortcuts — same as Chat composer. Keep these BEFORE
     * the plain-Enter branch so Ctrl+Enter / Alt+Enter don't fall through
     * to send(). Ctrl+M and Alt+V also toggle voice. */
    if (ev.key === "Enter" && (ev.ctrlKey || ev.altKey)) {
      ev.preventDefault();
      ev.stopPropagation(); /* prevent global voice handler from double-firing */
      if (typeof window.toggleVoiceInput === "function") {
        input.focus(); /* ensure _toggleVoice sees our textarea as active */
        window.toggleVoiceInput();
      }
      return;
    }
    if (
      (ev.ctrlKey && (ev.key === "m" || ev.key === "M")) ||
      (ev.altKey && (ev.key === "v" || ev.key === "V"))
    ) {
      ev.preventDefault();
      ev.stopPropagation();
      if (typeof window.toggleVoiceInput === "function") {
        input.focus();
        window.toggleVoiceInput();
      }
      return;
    }
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      send();
    } else if (ev.key === "Escape") {
      ev.preventDefault();
      close();
    }
  });
  /* Paste support — images / files / long text. Native paste of plain
   * text keeps the default behavior (lands in the textarea). If the
   * clipboard carries a file/image, route to the Chat composer (the
   * canonical paste-to-attach pipeline lives there) and re-dispatch
   * the paste event so the upload.js handler does the work.
   * ywatanabe 2026-04-19: "small input modal should support pasting". */
  input.addEventListener("paste", function (ev) {
    var cd =
      ev.clipboardData || (ev.originalEvent && ev.originalEvent.clipboardData);
    if (!cd) return;
    var hasFile = false;
    if (cd.files && cd.files.length) hasFile = true;
    else if (cd.items) {
      for (var i = 0; i < cd.items.length; i++) {
        var it = cd.items[i];
        if (it && it.type && it.type.indexOf("image/") === 0) {
          hasFile = true;
          break;
        }
      }
    }
    /* Long text still attaches as a file via upload.js's
     * _pastedTextShouldAttach heuristic — route for that case too. */
    var text = "";
    try {
      text = cd.getData("text/plain") || "";
    } catch (_) {}
    var isLong = text.length > 1000;
    if (hasFile || isLong) {
      ev.preventDefault();
      ev.stopPropagation();
      close();
      _routeToChat();
      setTimeout(function () {
        var msgInput = document.getElementById("msg-input");
        if (!msgInput) return;
        msgInput.focus();
        /* Synthesize a paste event on msg-input so upload.js's
         * handleClipboardPaste processes the same clipboard payload. */
        try {
          var newEv = new ClipboardEvent("paste", {
            clipboardData: cd,
            bubbles: true,
            cancelable: true,
          });
          msgInput.dispatchEvent(newEv);
        } catch (_) {
          /* Some browsers don't allow constructing ClipboardEvent with
           * populated data — let the user paste again in that case. */
        }
      }, 50);
    }
  });
  expandBtn.addEventListener("click", function () {
    var on = extras.style.display === "none";
    extras.style.display = on ? "" : "none";
    expandBtn.textContent = on ? "\u25B4" : "\u25BE";
  });
  /* Delegate extras — pop the channel into currentChannel so existing
   * global helpers target the right place, then invoke them. Fallback
   * to focusing the main composer for modes that don't have a headless
   * API surface. */
  function _routeToChat() {
    if (typeof setCurrentChannel === "function") setCurrentChannel(channel);
    if (typeof loadChannelHistory === "function") loadChannelHistory(channel);
    var tabBtn = document.querySelector('[data-tab="chat"]');
    if (tabBtn) tabBtn.click();
    close();
  }
  pop.querySelector(".tcc-attach").addEventListener("click", function () {
    _routeToChat();
    if (typeof openAttachmentPicker === "function") openAttachmentPicker();
  });
  pop.querySelector(".tcc-camera").addEventListener("click", function () {
    _routeToChat();
    if (typeof openCameraCapture === "function") openCameraCapture();
  });
  pop.querySelector(".tcc-sketch").addEventListener("click", function () {
    _routeToChat();
    if (typeof openSketchPanel === "function") openSketchPanel();
  });
  pop.querySelector(".tcc-voice").addEventListener("click", function () {
    /* Dictate into THIS popup's textarea — don't route to Chat.
     * Focus the popup textarea so _toggleVoice's selector-based
     * target resolution picks it up, then toggle. */
    if (typeof window.toggleVoiceInput === "function") {
      input.focus();
      window.toggleVoiceInput();
    }
  });
  /* Drop files onto popup → route to Chat with attachments primed. */
  pop.addEventListener("dragover", function (ev) {
    ev.preventDefault();
    pop.classList.add("tcc-drag-over");
  });
  pop.addEventListener("dragleave", function () {
    pop.classList.remove("tcc-drag-over");
  });
  pop.addEventListener("drop", function (ev) {
    ev.preventDefault();
    pop.classList.remove("tcc-drag-over");
    var files = ev.dataTransfer && ev.dataTransfer.files;
    if (files && files.length && typeof handleFileUpload === "function") {
      _routeToChat();
      for (var i = 0; i < files.length; i++) handleFileUpload(files[i]);
    }
  });
}

export function _topoSpawnGhost(svg, text, x, y) {
  var ns = "http://www.w3.org/2000/svg";
  var t = document.createElementNS(ns, "text");
  t.setAttribute("class", "topo-drag-ghost");
  t.setAttribute("x", x);
  t.setAttribute("y", y);
  t.setAttribute("pointer-events", "none");
  t.textContent = text;
  svg.appendChild(t);
  return t;
}
export function _topoShowSubscribeToast(agent, channel, perm) {
  if (typeof _showMiniToast === "function") {
    var verb = perm === "read-write" ? "read-write" : "read-only";
    _showMiniToast(
      "Added " + agent + " to " + channel + " (" + verb + ")",
      "ok",
    );
  }
}

// Expose cross-file mutable state via globalThis:
(globalThis as any)._topoDragState = (typeof _topoDragState !== 'undefined' ? _topoDragState : undefined);
