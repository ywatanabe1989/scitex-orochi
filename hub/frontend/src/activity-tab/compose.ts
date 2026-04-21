// @ts-nocheck
import { _activityChannelRequest, _invalidateTopoPerms } from "./data";
import { _graphFeedSetChannel } from "./graph-feed";
import { _showMiniToast } from "../app/agent-actions";
import { _channelPrefs } from "../app/members";
import { fetchAgents } from "../app/sidebar-agents";
import { setCurrentChannel } from "../app/state";
import { apiUrl, escapeHtml, sendOrochiMessage, userName } from "../app/utils";
import { ws, wsConnected } from "../app/websocket";
import { loadChannelHistory } from "../chat/chat-history";
import {
  _buildPastedTextFile,
  _pastedTextShouldAttach,
  _uploadFilesAPI,
} from "../upload";

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
  /* Item 15 (lead msg#15694): channel-node double-click now shows a
   * last-5-messages preview ABOVE the input area, so the user can see
   * the conversation context before replying without first having to
   * hover (channel-hover-preview popover) or triple-click into the
   * full Chat tab. The preview is chronological (oldest → newest),
   * scrolls internally if content overflows, and renders a loading
   * placeholder while the fetch is in flight; a failed fetch turns
   * into a muted "(no recent messages)" row rather than an error
   * block so the compose input stays usable. */
  pop.innerHTML =
    '<div class="tcc-preview" data-tcc-preview>' +
    '<div class="tcc-preview-loading">Loading recent messages\u2026</div>' +
    "</div>" +
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
  /* Item 15: fire off a last-5 history fetch. This is fire-and-forget
   * — no await, no blocking of the compose input. If the popup has
   * been closed by the time the response lands, the querySelector
   * returns null and we silently skip painting. */
  _tccLoadPreview(pop, channel);
  /* Wire the persistent graph feed to this channel so replies to the
   * outgoing post land in the right-docked panel instead of flashing
   * off-screen as a 1.3s landing bubble (lead msg#15701 blocker). */
  if (typeof _graphFeedSetChannel === "function") {
    try {
      _graphFeedSetChannel(channel);
    } catch (_) {}
  }
  var input = pop.querySelector(".tcc-input");
  var extras = pop.querySelector(".tcc-extras");
  var expandBtn = pop.querySelector(".tcc-expand");
  setTimeout(function () {
    if (input) input.focus();
  }, 10);

  /* todo#305 Task 6 (lead msg#15528): Cmd+V / ⌘V / context-menu Paste
   * was failing on this popup. Root cause: macOS Safari does NOT focus
   * a textarea on right-click (unlike Chrome/Firefox). A right-click on
   * our textarea therefore left document.activeElement on whatever had
   * focus before the popup opened (often <body> or the topology
   * canvas), so the subsequent native "Paste" from the OS context menu
   * fired a paste event on THAT element — not the textarea.
   *
   * Keyboard Cmd+V was only intermittent for the same reason: if the
   * user clicked anywhere inside the popup that wasn't a focusable
   * child, the textarea could lose focus and the next Cmd+V landed
   * outside.
   *
   * Fix: refocus the textarea on ANY pointer interaction inside the
   * popup (mousedown covers left + right click + middle click on all
   * browsers), unless the target is one of the action buttons that
   * legitimately owns focus (attach / camera / sketch / voice /
   * expand). Also listen to `contextmenu` explicitly — belt & braces
   * for browsers that fire contextmenu without a prior mousedown
   * (some trackpad two-finger-tap paths on macOS). */
  function _refocusInput(ev) {
    if (!input) return;
    /* Don't steal focus from action buttons. */
    if (
      ev.target &&
      ev.target.closest &&
      ev.target.closest(".tcc-x, .tcc-expand")
    ) {
      return;
    }
    /* If the user clicked directly on the textarea, the browser will
     * focus it anyway and move the caret — don't fight that. Only
     * refocus when the target is a non-focusable child (the popup
     * chrome, a label, etc.) or the textarea but unfocused (e.g.
     * right-click on macOS Safari). */
    if (document.activeElement !== input) {
      try {
        input.focus();
      } catch (_) {}
    }
  }
  pop.addEventListener("mousedown", _refocusInput);
  pop.addEventListener("contextmenu", _refocusInput);

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

  /* msg#16193: local-scoped pending attachments for this popup. Paste /
   * drop stage here instead of routing to the Chat composer, so the
   * user's Overview-tab interaction never flips them into Chat. Rendered
   * as a small inline strip ABOVE the textarea; cleared when the popup
   * closes or the message is sent. */
  var popPending = [];
  var popTray = document.createElement("div");
  popTray.className = "tcc-pending";
  popTray.style.display = "none";
  /* Insert above the textarea (after preview slot if present). */
  if (input && input.parentNode === pop) {
    pop.insertBefore(popTray, input);
  } else {
    pop.insertBefore(popTray, pop.firstChild);
  }

  function _renderPopTray() {
    if (!popPending.length) {
      popTray.style.display = "none";
      popTray.innerHTML = "";
      return;
    }
    popTray.style.display = "flex";
    popTray.innerHTML = "";
    popPending.forEach(function (p, idx) {
      var item = document.createElement("div");
      item.className = "tcc-pending-item";
      var isImage =
        p.uploaded &&
        p.uploaded.mime_type &&
        p.uploaded.mime_type.indexOf("image/") === 0;
      var thumb;
      if (isImage) {
        thumb = document.createElement("img");
        thumb.src = p.uploaded.url;
        thumb.className = "tcc-pending-thumb";
        thumb.alt = p.uploaded.filename || "image";
      } else {
        thumb = document.createElement("span");
        thumb.className = "tcc-pending-icon";
        thumb.textContent = "\uD83D\uDCCE";
      }
      var label = document.createElement("span");
      label.className = "tcc-pending-label";
      label.textContent = (p.uploaded && p.uploaded.filename) || "";
      var remove = document.createElement("button");
      remove.type = "button";
      remove.className = "tcc-pending-remove";
      remove.title = "Remove";
      remove.textContent = "\u2715";
      remove.addEventListener("click", function (ev) {
        ev.stopPropagation();
        popPending.splice(idx, 1);
        _renderPopTray();
      });
      item.appendChild(thumb);
      item.appendChild(label);
      item.appendChild(remove);
      popTray.appendChild(item);
    });
  }

  async function _stagePopFiles(files) {
    if (!files || files.length === 0) return;
    var uploaded = await _uploadFilesAPI(files);
    if (!uploaded || !uploaded.length) return;
    /* Popup may have closed while upload was in-flight — bail silently. */
    if (!pop.parentNode) return;
    uploaded.forEach(function (u, i) {
      popPending.push({ file: files[i] || files[0], uploaded: u });
    });
    _renderPopTray();
  }

  function send() {
    var text = (input.value || "").trim();
    var attachments = popPending.map(function (p) {
      return p.uploaded;
    });
    if (!text && attachments.length === 0) return;
    var payload = { channel: channel, content: text };
    if (attachments.length > 0) payload.attachments = attachments;
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
    /* msg#16316 / ywatanabe msg#16313: keep the popup OPEN after send so
     * the user can keep replying without re-double-clicking the channel
     * node. Clear the textarea + pending attachment tray, refocus the
     * input, and leave the popup mounted. The popup still closes via
     * Esc, outside-click, or routing to Chat (existing paths). */
    input.value = "";
    popPending.length = 0;
    _renderPopTray();
    try {
      input.focus();
    } catch (_) {}
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
  /* Paste support — images / files / long text. msg#16193 regression-fix:
   * previously this handler, on image/long-text paste, closed the popup
   * and re-dispatched the paste into the Chat composer via `_routeToChat`
   * — which flipped the user out of the Overview tab, which is exactly
   * the bug the user keeps reporting ("I'm on Overview, I paste an
   * image, I end up on Chat"). Fix: stage attachments LOCALLY to this
   * popup (upload to /api/upload, show inline thumb strip, include in
   * the send() payload). No tab switch, no msg-input re-dispatch.
   *
   * Keep `ev.stopPropagation()` so nothing bubbles into msg-input's
   * window-level paste handler. Short plain text still lands in the
   * textarea via the browser's default paste behavior (we only
   * preventDefault when we actually stage a file). */
  input.addEventListener("paste", function (ev) {
    ev.stopPropagation();
    var cd =
      ev.clipboardData || (ev.originalEvent && ev.originalEvent.clipboardData);
    if (!cd) return;
    /* Collect image files from both cd.files (browsers that expose it)
     * and cd.items (browsers that only expose items). Dedup inline. */
    var collected = [];
    var seen = new Set();
    function pushUnique(f) {
      if (!f || !f.type || f.type.indexOf("image/") !== 0) return;
      var key =
        f.name + "|" + f.size + "|" + f.type + "|" + (f.lastModified || 0);
      if (seen.has(key)) return;
      seen.add(key);
      collected.push(f);
    }
    var fileList = cd.files;
    if (fileList && fileList.length) {
      for (var i = 0; i < fileList.length; i++) pushUnique(fileList[i]);
    } else if (cd.items) {
      for (var j = 0; j < cd.items.length; j++) {
        var it = cd.items[j];
        if (it && it.type && it.type.indexOf("image/") === 0) {
          pushUnique(it.getAsFile());
        }
      }
    }
    /* Long-text-as-file: same heuristic as upload.ts (>= 1500 chars or
     * >= 25 lines) so the popup behaves identically to the Chat
     * composer in this regard. */
    var text = "";
    try {
      text = cd.getData("text/plain") || "";
    } catch (_) {}
    var attachText =
      typeof _pastedTextShouldAttach === "function" &&
      _pastedTextShouldAttach(text);
    if (collected.length > 0 || attachText) {
      ev.preventDefault();
      if (attachText && typeof _buildPastedTextFile === "function") {
        collected.push(_buildPastedTextFile(text));
      }
      _stagePopFiles(collected);
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
  /* Drop files onto popup → stage LOCALLY (msg#16193). Same rationale
   * as the paste handler: the user is working in the graph-compose
   * popup on the Overview tab and shouldn't get flipped to Chat for a
   * drag-drop. */
  pop.addEventListener("dragover", function (ev) {
    ev.preventDefault();
    ev.stopPropagation();
    pop.classList.add("tcc-drag-over");
  });
  pop.addEventListener("dragleave", function () {
    pop.classList.remove("tcc-drag-over");
  });
  pop.addEventListener("drop", function (ev) {
    ev.preventDefault();
    ev.stopPropagation();
    pop.classList.remove("tcc-drag-over");
    var files = ev.dataTransfer && ev.dataTransfer.files;
    if (files && files.length) {
      _stagePopFiles(Array.prototype.slice.call(files));
    }
  });
}

/* Item 15 (lead msg#15694): fetch & render the last 5 messages for
 * the double-clicked channel inside the compose popup's .tcc-preview
 * slot. Runs fire-and-forget — never blocks the input or closes the
 * popup on failure. API shape mirrors /api/history/ as used by
 * graph-feed / channel-hover-preview (newest-first; we reverse to
 * chronological before rendering). */
var _TCC_PREVIEW_LIMIT = 5;
function _tccFmtTime(iso) {
  if (!iso) return "";
  try {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    var hh = String(d.getHours()).padStart(2, "0");
    var mm = String(d.getMinutes()).padStart(2, "0");
    return hh + ":" + mm;
  } catch (_e) {
    return "";
  }
}
function _tccTruncate(s, n) {
  if (!s) return "";
  s = String(s);
  if (s.length <= n) return s;
  return s.slice(0, n - 1) + "\u2026";
}
function _tccRenderRows(rows) {
  if (!rows || !rows.length) {
    return '<div class="tcc-preview-empty">(no recent messages)</div>';
  }
  return rows
    .map(function (m) {
      var sender = m.sender || "?";
      var ts = _tccFmtTime(m.ts);
      var content = _tccTruncate(m.content || "", 140);
      return (
        '<div class="tcc-preview-row">' +
        '<div class="tcc-preview-meta">' +
        '<span class="tcc-preview-sender">' +
        escapeHtml(sender) +
        "</span>" +
        (ts
          ? '<span class="tcc-preview-ts">' + escapeHtml(ts) + "</span>"
          : "") +
        "</div>" +
        '<div class="tcc-preview-body">' +
        escapeHtml(content) +
        "</div>" +
        "</div>"
      );
    })
    .join("");
}
function _tccLoadPreview(pop, channel) {
  if (!pop || !channel) return;
  var encoded = encodeURIComponent(channel);
  var url = apiUrl(
    "/api/history/" + encoded + "?limit=" + _TCC_PREVIEW_LIMIT,
  );
  fetch(url, { credentials: "same-origin" })
    .then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    })
    .then(function (rows) {
      /* Bail quietly if the popup is already gone (user pressed Esc,
       * clicked outside, or double-clicked another channel). */
      if (!pop.parentNode) return;
      if (pop.getAttribute("data-channel") !== channel) return;
      var slot = pop.querySelector("[data-tcc-preview]");
      if (!slot) return;
      /* API returns newest-first; flip so the compose preview reads
       * chronologically (oldest → newest, same as Chat feed). */
      var chrono = (rows || []).slice().reverse();
      slot.innerHTML = _tccRenderRows(chrono);
      /* Keep the latest message visible when overflow clips the
       * preview — users care most about what they're about to reply
       * to, which sits at the bottom. */
      slot.scrollTop = slot.scrollHeight;
    })
    .catch(function () {
      if (!pop.parentNode) return;
      var slot = pop.querySelector("[data-tcc-preview]");
      if (slot) {
        slot.innerHTML =
          '<div class="tcc-preview-empty">(no recent messages)</div>';
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
