/* Orochi Dashboard -- bootstrap (loaded last) */
/* globals: loadHistory, fetchStats, fetchAgents, connect, fetchTodoList,
   fetchResources, fetchWorkspaces, wsConnected, startRestPolling,
   getSnakeLogo, refreshAgentNames */

/* Inject Orochi logo into sidebar brand. Size/radius come from CSS
 * (.brand-logo-sm .header-icon rule in style-base.css) so the compact
 * header can shrink it to 22px without fighting inline styles. */
(function () {
  var brandLogo = document.getElementById("brand-logo");
  if (brandLogo) {
    brandLogo.innerHTML =
      '<img class="header-icon" src="/static/hub/orochi-icon.png" alt="Orochi">';
  }
})();

/* Inject workspace icon into sidebar selector.
 * Render cascade: uploaded image > emoji > first-letter coloured square.
 * getWorkspaceIcon() handles branches (1) and (3); the emoji branch is
 * handled here because it's a simple text span. */
(function () {
  var wsIconSlot = document.getElementById("ws-icon-slot");
  var wsName = window.__orochiWorkspaceName || "workspace";
  var wsIconImage = window.__orochiWorkspaceIconImage || "";
  var wsIcon = window.__orochiWorkspaceIcon || "";
  if (wsIconSlot) {
    if (wsIconImage) {
      wsIconSlot.innerHTML = getWorkspaceIcon(wsName, 16);
    } else if (wsIcon) {
      wsIconSlot.innerHTML =
        '<span class="ws-emoji-icon">' + wsIcon + "</span>";
    } else {
      wsIconSlot.innerHTML = getWorkspaceIcon(wsName, 16);
    }
  }
})();

/* Wall clock for screenshot timestamps (#342).
 * Render in the user's browser locale (no hard-coded TZ) per #155:
 * timestamps are UTC at rest on the hub, displayed in local TZ at the UI.
 * Pass `undefined` for locale so Intl uses the browser default; omit
 * timeZone so it falls back to the user's system TZ. */
(function () {
  var el = document.getElementById("wall-clock");
  if (!el) return;
  function tick() {
    el.textContent = new Date().toLocaleString(undefined, {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  }
  tick();
  setInterval(tick, 1000);
})();

refreshAgentNames().then(function () {
  loadHistory();
});
fetchAgents();
/* Per-user avatars — populate cachedHumanIcons/Colors so other users'
 * chosen emoji/image/color render across the dashboard. */
if (typeof fetchHumanProfiles === "function") {
  fetchHumanProfiles();
  setInterval(fetchHumanProfiles, 60000);
}
fetchStats();
connect();
setInterval(fetchStats, 10000);
setInterval(fetchAgents, 10000);
fetchTodoList();
setInterval(fetchTodoList, 60000);
fetchResources();
setInterval(fetchResources, 30000);
fetchWorkspaces();
setInterval(fetchWorkspaces, 30000);
setTimeout(function () {
  if (!wsConnected) {
    console.warn("WebSocket not connected after 3s, starting REST poll");
    startRestPolling();
  }
}, 3000);

/* Global Escape key handler — closes any open popup/modal/overlay.
 * Checks in order of most-foreground to least, closing only the top one
 * per keypress so stacked popups dismiss one at a time. */
document.addEventListener("keydown", function (e) {
  if (e.key !== "Escape") return;

  /* Skip if user is editing a message (chat.js handles its own ESC) */
  var editInput = document.querySelector(".msg-edit-input");
  if (editInput && document.activeElement === editInput) return;

  /* Skip if element inspector is active (it handles its own ESC) */
  if (window.elementInspector && window.elementInspector._isActive) return;

  /* 1. Emoji picker overlay */
  var emojiOverlay = document.querySelector(".emoji-picker-overlay.visible");
  if (emojiOverlay) {
    if (typeof window.closeEmojiPicker === "function")
      window.closeEmojiPicker();
    e.preventDefault();
    return;
  }

  /* 2. Reaction picker */
  if (typeof reactionPicker !== "undefined" && reactionPicker) {
    closeReactionPicker();
    e.preventDefault();
    return;
  }

  /* 3. Sketch overlay */
  if (typeof sketchOverlay !== "undefined" && sketchOverlay) {
    /* sketch.js registers its own per-instance ESC handler, but this
     * serves as a safety net in case that listener was removed. */
    closeSketch();
    e.preventDefault();
    return;
  }

  /* 4. Thread panel */
  if (typeof threadPanel !== "undefined" && threadPanel) {
    closeThreadPanel();
    e.preventDefault();
    return;
  }

  /* 5. Mention dropdown */
  var mentionDD = document.getElementById("mention-dropdown");
  if (mentionDD && mentionDD.classList.contains("visible")) {
    if (typeof hideMentionDropdown === "function") hideMentionDropdown();
    e.preventDefault();
    return;
  }

  /* 6. Filter suggest dropdown */
  var filterDD = document.getElementById("filter-suggest");
  if (filterDD && filterDD.classList.contains("visible")) {
    filterDD.classList.remove("visible");
    filterDD.innerHTML = "";
    e.preventDefault();
    return;
  }

  /* 7. Agent detail popup */
  var openDetail = document.querySelector(".agent-detail-popup.open");
  if (openDetail) {
    openDetail.classList.remove("open");
    e.preventDefault();
    return;
  }

  /* 8. Workspace dropdown (handled by its own IIFE, but kept as fallback) */
  var wsDropdown = document.querySelector(".ws-dropdown");
  if (wsDropdown) {
    /* The IIFE listener will catch this too; no-op here to avoid double-close. */
    return;
  }

  /* 9. Mobile sidebar */
  var sidebar = document.getElementById("sidebar");
  if (sidebar && sidebar.classList.contains("open")) {
    sidebar.classList.remove("open");
    var toggle = document.getElementById("sidebar-toggle");
    if (toggle) {
      toggle.classList.remove("open");
      toggle.innerHTML = "&#9776;";
    }
    var backdrop = document.querySelector(".sidebar-backdrop");
    if (backdrop) backdrop.classList.remove("visible");
    e.preventDefault();
    return;
  }
});
