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
var _topoComposeEl = null;
var _topoComposeEscapeHandler = null;

function _closeTopoGroupCompose() {
  if (_topoComposeEl && _topoComposeEl.parentNode) {
    _topoComposeEl.parentNode.removeChild(_topoComposeEl);
  }
  _topoComposeEl = null;
  if (_topoComposeEscapeHandler) {
    document.removeEventListener("keydown", _topoComposeEscapeHandler, true);
    _topoComposeEscapeHandler = null;
  }
}

function _openTopoGroupCompose(agents) {
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

function _submitTopoMentionPost(channel, agents, text) {
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

async function _submitTopoGroupDmPost(agents, text) {
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
function _topoClearDrop() {
  if (!_topoDragState) return;
  if (_topoDragState.lastDrop) {
    _topoDragState.lastDrop.classList.remove("topo-drop-target");
    _topoDragState.lastDrop = null;
  }
}
function _topoCleanupDrag() {
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
function _topoOpenChannelCompose(channel, clientX, clientY) {
  /* Kill any previous popup first. */
  var prev = document.getElementById("topo-channel-compose");
  if (prev && prev.parentNode) prev.parentNode.removeChild(prev);
  var pop = document.createElement("div");
  pop.id = "topo-channel-compose";
  pop.className = "topo-channel-compose";
  pop.setAttribute("data-channel", channel);
  pop.setAttribute("data-composer-surface", "overview");
  pop.style.left = Math.max(8, clientX - 140) + "px";
  pop.style.top = Math.max(8, clientY + 12) + "px";
  var tccShortcuts =
    "Enter — send\n" +
    "Shift+Enter — newline\n" +
    "Esc — close\n" +
    "Drop files to attach\n" +
    "Paste image/file to attach\n" +
    "Click ▾ for attach / camera / sketch / voice";
  /* Preview slot + pending tray + composer slot + chevron. Composer DOM
   * injected by renderComposer into .tcc-composer-slot; its action row
   * is moved into .tcc-extras so the chevron can toggle visibility
   * (matches pre-SSoT UX). */
  pop.innerHTML =
    '<div class="tcc-pending" style="display:none"></div>' +
    '<div class="tcc-composer-slot"></div>' +
    '<button type="button" class="tcc-expand" title="' +
    tccShortcuts.replace(/"/g, "&quot;") +
    '" aria-label="More options">\u25BE</button>';
  document.body.appendChild(pop);

  var popTray = pop.querySelector(".tcc-pending");
  var composerSlot = pop.querySelector(".tcc-composer-slot");
  var expandBtn = pop.querySelector(".tcc-expand");

  var popPending = [];

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
    var uploaded =
      typeof _uploadFilesAPI === "function" ? await _uploadFilesAPI(files) : [];
    if (!uploaded || !uploaded.length) return;
    if (!pop.parentNode) return;
    uploaded.forEach(function (u, i) {
      popPending.push({ file: files[i] || files[0], uploaded: u });
    });
    _renderPopTray();
  }

  /* Build composer via SSoT module. Mention autocomplete, paste, attach/
   * camera/sketch/voice, keyboard shortcuts — all shared with Chat + Reply. */
  var composerInstance =
    typeof renderComposer === "function"
      ? renderComposer(composerSlot, {
          surface: "overview",
          placeholder:
            "message #" + String(channel || "").replace(/^#/, ""),
          stageFiles: _stagePopFiles,
          features: {
            mention: true,
            paste: true,
            dragDrop: false,
            attach: true,
            camera: true,
            sketch: true,
            voice: true,
            sendButton: false,
            shiftEnterNewline: true,
            autoResize: false,
            cmdEnterSubmit: true,
            tabAwareFocus: false,
            localVoiceChord: true,
          },
          maxResizePx: 0,
          onSubmit: function () {
            send();
          },
        })
      : null;
  var input = composerInstance ? composerInstance.input : null;
  if (input) {
    input.classList.add("tcc-input");
    input.title = tccShortcuts;
    input.rows = 2;
  }

  /* Move composer action row into .tcc-extras so the chevron can toggle. */
  var actionsRow = composerSlot.querySelector(".composer-actions");
  var extras = document.createElement("div");
  extras.className = "tcc-extras";
  extras.style.display = "none";
  if (actionsRow) extras.appendChild(actionsRow);
  composerSlot.appendChild(extras);

  var actionBtns = extras.querySelectorAll(".composer-btn");
  actionBtns.forEach(function (b) {
    b.classList.add("tcc-x");
    if (b.classList.contains("composer-btn-attach")) b.classList.add("tcc-attach");
    else if (b.classList.contains("composer-btn-camera")) b.classList.add("tcc-camera");
    else if (b.classList.contains("composer-btn-sketch")) b.classList.add("tcc-sketch");
    else if (b.classList.contains("composer-btn-voice")) b.classList.add("tcc-voice");
  });

  /* msg#16324: restore any persisted draft + wire debounced save. */
  try {
    if (
      typeof window.orochiDraftStore !== "undefined" &&
      window.orochiDraftStore
    ) {
      var _saved = window.orochiDraftStore.loadDraft("overview-popup", channel);
      if (input && _saved) input.value = _saved;
    }
  } catch (_) {}
  if (input) {
    input.addEventListener("input", function () {
      try {
        if (
          typeof window.orochiDraftStore !== "undefined" &&
          window.orochiDraftStore &&
          typeof window.orochiDraftStore._debounceSave === "function"
        ) {
          window.orochiDraftStore._debounceSave(
            "overview-popup",
            channel,
            input.value,
          );
        }
      } catch (_) {}
    });
  }
  setTimeout(function () {
    if (input) {
      try {
        input.focus();
        var _len = input.value ? input.value.length : 0;
        input.setSelectionRange(_len, _len);
      } catch (_) {}
    }
  }, 10);

  /* todo#305 Task 6 (lead msg#15528): Cmd+V / ⌘V / context-menu Paste
   * was failing on this popup. Refocus the textarea on ANY pointer
   * interaction inside the popup unless the target is an action button. */
  function _refocusInput(ev) {
    if (!input) return;
    if (
      ev.target &&
      ev.target.closest &&
      ev.target.closest(".tcc-x, .tcc-expand, .composer-btn")
    ) {
      return;
    }
    if (document.activeElement !== input) {
      try { input.focus(); } catch (_) {}
    }
  }
  pop.addEventListener("mousedown", _refocusInput);
  pop.addEventListener("contextmenu", _refocusInput);

  function close() {
    try { if (composerInstance) composerInstance.destroy(); } catch (_) {}
    if (pop.parentNode) pop.parentNode.removeChild(pop);
    document.removeEventListener("mousedown", outsideClick, true);
  }
  function outsideClick(ev) {
    if (!pop.contains(ev.target)) close();
  }
  setTimeout(function () {
    document.addEventListener("mousedown", outsideClick, true);
  }, 50);

  /* Esc closes the popup; Enter / Shift+Enter handled by composer. */
  if (input) {
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") {
        ev.preventDefault();
        close();
      }
    });
  }

  function send() {
    if (!input) return;
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
    /* msg#16316: keep popup OPEN after send; clear textarea + tray. */
    input.value = "";
    popPending.length = 0;
    _renderPopTray();
    /* msg#16324: clear the stored draft ONLY on successful send. */
    try {
      if (
        typeof window.orochiDraftStore !== "undefined" &&
        window.orochiDraftStore &&
        typeof window.orochiDraftStore.clearDraft === "function"
      ) {
        window.orochiDraftStore.clearDraft("overview-popup", channel);
      }
    } catch (_) {}
    try { input.focus(); } catch (_) {}
  }

  expandBtn.addEventListener("click", function () {
    var on = extras.style.display === "none";
    extras.style.display = on ? "" : "none";
    expandBtn.textContent = on ? "\u25B4" : "\u25BE";
  });

  /* Drop files onto popup → stage LOCALLY (msg#16193). */
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

function _topoSpawnGhost(svg, text, x, y) {
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
function _topoShowSubscribeToast(agent, channel, perm) {
  if (typeof _showMiniToast === "function") {
    var verb = perm === "read-write" ? "read-write" : "read-only";
    _showMiniToast(
      "Added " + agent + " to " + channel + " (" + verb + ")",
      "ok",
    );
  }
}

