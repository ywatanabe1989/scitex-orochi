// @ts-nocheck
import { refreshActivityFromApi, startActivityAutoRefresh } from "./activity-tab/data";
import { renderAgentsTab } from "./agents-tab/overview";
import { restoreDraftForCurrentChannel } from "./chat/chat-composer";
import { loadChannelHistory } from "./chat/chat-history";
import { fetchFiles } from "./files-tab/files-tab-grid";
import { renderResourcesTab } from "./resources-tab/tab";
import { fetchSettings } from "./settings-tab";
import { renderTerminalTab } from "./terminal-tab";
import { fetchTodoList } from "./todo-tab/todo-tab-list";
import { renderVizTab, stopVizTab } from "./viz-tab";
import { fetchWorkspaces } from "./workspaces-tab";
import { setCurrentChannel } from "./app/state";
import { channelUnread } from "./app/utils";

/* Tab switching, collapsible sections, mobile sidebar */
/* globals: activeTab, fetchTodoList, renderAgentsTab, renderResourcesTab,
   fetchWorkspaces */

/* Default landing tab — the Overview tab (internal id "activity" — see
 * note below) is the leftmost tab and the first-load landing surface.
 * The internal id stays "activity" even though the user-visible label
 * reads "Overview"; renaming the id would churn every globalThis/SSE
 * key that keys off it (_overviewExpanded, etc.), and the directory
 * name `activity-tab/` is likewise left alone per Step 3 spec. */
export var activeTab = "activity";

/* PR #<this> Item 3 helper: pick a sensible default channel when the
 * Chat tab is activated without one. Preference order:
 *   1. Channel with the highest unread count (proxy for "most recently
 *      posted / most relevant right now").
 *   2. First sidebar channel row in document order (i.e. first in the
 *      user's star-sorted list).
 * Returns null if no candidate exists (empty sidebar / first load
 * before the stats fetch returns). Caller is responsible for null
 * handling — we intentionally do NOT set a placeholder channel. */
function _pickFallbackChannel(): string | null {
  try {
    /* 1. Highest unread. channelUnread keys are channel names (raw or
     *    normalised). We filter out DM channels since those are owned
     *    by the DM surface; Chat fallback should land on a group
     *    channel. */
    var best: string | null = null;
    var bestCount = 0;
    var unread = (channelUnread as Record<string, number>) || {};
    Object.keys(unread).forEach(function (k) {
      if (!k || k.indexOf("dm:") === 0) return;
      var n = unread[k] || 0;
      if (n > bestCount) {
        bestCount = n;
        best = k;
      }
    });
    if (best) return best;
    /* 2. First sidebar channel row. Skip hidden/dm rows. */
    var row = document.querySelector(
      '.sidebar .channel-item:not([data-hidden="1"])',
    );
    if (row) {
      var ch = row.getAttribute("data-channel");
      if (ch && ch.indexOf("dm:") !== 0) return ch;
    }
  } catch (_) {
    /* Never let a fallback-pick error break the tab activation. */
  }
  return null;
}

export function _activateTab(tab) {
  activeTab = tab;
  document.querySelectorAll(".tab-btn").forEach(function (b) {
    b.classList.toggle("active", b.getAttribute("data-tab") === tab);
  });
  var messagesEl = document.getElementById("messages");
  var chatFilterEl = document.getElementById("chat-filter-input");
  var inputBar = document.querySelector(".input-bar");
  var todoView = document.getElementById("todo-view");
  var resourcesView = document.getElementById("resources-view");
  var agentsTabView = document.getElementById("agents-tab-view");
  var workspacesView = document.getElementById("workspaces-view");
  var activityView = document.getElementById("activity-view");
  var filesView = document.getElementById("files-view");
  var releasesView = document.getElementById("releases-view");
  var terminalView = document.getElementById("terminal-view");
  var settingsView = document.getElementById("settings-view");
  messagesEl.style.display = "none";
  if (chatFilterEl) chatFilterEl.style.display = "none";
  inputBar.style.display = "none";
  var topicBanner = document.getElementById("channel-topic-banner");
  if (topicBanner) topicBanner.style.display = "none";
  var membersPanel = document.getElementById("channel-members-panel");
  if (membersPanel) membersPanel.style.display = "none";
  todoView.style.display = "none";
  resourcesView.style.display = "none";
  agentsTabView.style.display = "none";
  workspacesView.style.display = "none";
  if (activityView) activityView.style.display = "none";
  if (filesView) filesView.style.display = "none";
  if (releasesView) releasesView.style.display = "none";
  if (terminalView) terminalView.style.display = "none";
  if (settingsView) settingsView.style.display = "none";
  /* Viz lives inside #todo-view; its poll is owned by todo-tab.js.
   * When the TODO tab is left, todo-tab.js stops the viz poll. */
  if (tab !== "todo" && typeof stopVizTab === "function") stopVizTab();
  if (tab === "chat") {
    messagesEl.style.display = "";
    if (chatFilterEl) chatFilterEl.style.display = "";
    inputBar.style.display = "";
    /* Restore the channel-topic banner on re-entry to Chat. The block at
     * the top of _activateTab hides it unconditionally; we only want that
     * when leaving chat, not when returning. Without this line the banner
     * vanishes after the first tab switch. Banner content already tracks
     * the textarea target (see app.js _updateChannelTopicBanner). */
    if (topicBanner) topicBanner.style.display = "";
    /* PR #<this> Item 3: Chat tab single-channel enforcement. On mount,
     * if no channel is currently selected (and we're not in a DM), auto-
     * select a reasonable default — prefer the channel with the most
     * unread messages (closest proxy to "most recently posted"), fall
     * back to the first visible sidebar channel. Never leave the Chat
     * tab in the "Type a message (no channel selected)" state from its
     * normal flow — that placeholder should only be reachable from the
     * all-channels filter entry, never from Chat's mount path.
     *
     * DM exception: if the user is in a DM thread (currentChannel starts
     * with "dm:"), we don't interfere — DMs are first-class chat
     * targets. */
    var cur = (globalThis as any).currentChannel;
    var inDm = typeof cur === "string" && cur.indexOf("dm:") === 0;
    if (!cur && !inDm) {
      var picked = _pickFallbackChannel();
      if (picked) {
        setCurrentChannel(picked);
        if (typeof loadChannelHistory === "function")
          loadChannelHistory(picked);
        /* Flip .selected on the sidebar row so the visual matches the
         * state; the full sidebar re-render on next stats fetch will
         * idempotently do the same, but this makes the transition feel
         * instant. */
        document
          .querySelectorAll(
            ".sidebar .channel-item.selected, .sidebar .dm-item.selected",
          )
          .forEach(function (it) {
            it.classList.remove("selected");
          });
        var row = document.querySelector(
          '.sidebar .channel-item[data-channel="' +
            picked.replace(/"/g, '\\"') +
            '"]',
        );
        if (row) row.classList.add("selected");
      }
    }
    /* Always default-focus the compose input when the chat tab is shown.
     * Per ywatanabe spec (msg 5470, 2026-04-12): the compose textarea is
     * the primary action target on the chat tab, so the user should never
     * have to click into it manually after switching tabs or reloading.
     * Defer with rAF so the layout has settled (display:'' just changed). */
    requestAnimationFrame(function () {
      /* Snap to bottom whenever chat is shown — initial load + every
       * tab-switch back to chat. Layout may not be final until after the
       * rAF tick, so scroll here (not synchronously). */
      messagesEl.scrollTop = messagesEl.scrollHeight;
      var input = document.getElementById("msg-input");
      if (input) {
        input.focus();
        if (typeof restoreDraftForCurrentChannel === "function") {
          restoreDraftForCurrentChannel();
        }
      }
    });
  } else if (tab === "todo") {
    todoView.style.display = "block";
    todoView.style.flex = "1";
    fetchTodoList();
    /* Viz is always rendered at the top of the TODO tab (todo#82).
     * Re-activate it on tab re-entry so the poll timer restarts and a
     * cached chart paints instantly from memory. */
    if (typeof renderVizTab === "function") renderVizTab();
  } else if (tab === "agents-tab") {
    agentsTabView.style.display = "block";
    agentsTabView.style.flex = "1";
    renderAgentsTab();
  } else if (tab === "resources") {
    resourcesView.style.display = "block";
    resourcesView.style.flex = "1";
    renderResourcesTab();
  } else if (tab === "workspaces") {
    workspacesView.style.display = "block";
    workspacesView.style.flex = "1";
    fetchWorkspaces();
  } else if (tab === "activity") {
    if (activityView) {
      /* Clear the inline display:none set above and let the CSS rule
       * (#activity-view.todo-view { display: flex }) take effect. An
       * inline `display: block` here would override the flex container
       * declaration, which breaks the flex chain and prevents
       * `.activity-grid` from scrolling (its `overflow: auto` never has
       * an upper bound to trigger against). See #200 for the CSS side. */
      activityView.style.display = "";
      activityView.style.flex = "1";
    }
    if (typeof refreshActivityFromApi === "function") refreshActivityFromApi();
    if (typeof startActivityAutoRefresh === "function")
      startActivityAutoRefresh();
  } else if (tab === "files") {
    if (filesView) {
      filesView.style.display = "block";
      filesView.style.flex = "1";
    }
    if (typeof fetchFiles === "function") fetchFiles();
  } else if (tab === "releases") {
    if (releasesView) {
      releasesView.style.display = "block";
      releasesView.style.flex = "1";
    }
    if (typeof fetchReleases === "function") fetchReleases();
  } else if (tab === "terminal") {
    if (terminalView) {
      terminalView.style.display = "flex";
      terminalView.style.flex = "1";
    }
    if (typeof renderTerminalTab === "function") renderTerminalTab();
  } else if (tab === "settings" && settingsView) {
    settingsView.style.display = "block";
    settingsView.style.flex = "1";
    fetchSettings();
  }
  try {
    localStorage.setItem("orochi_active_tab", tab);
  } catch (_) {}
}

/* msg#16116 Item 3: cmd-click / ctrl-click / middle-click on a tab
 * button should open that view in a new browser tab so the user can
 * lay Overview + TODO side-by-side. Tab buttons are <button> elements
 * (dashboard.html), not <a>, so browsers don't offer the native
 * "open in new tab" affordance by default. Rather than change the
 * markup (which would cascade into every .tab-btn CSS selector), we
 * intercept modifier-key and middle clicks at the JS layer:
 *   - auxclick listener catches middle-button presses and calls
 *     window.open(pathname + "#tab", "_blank").
 *   - Regular click listener checks metaKey / ctrlKey / shiftKey; if
 *     any is pressed, preventDefault and route through window.open.
 *   - Plain left-click still runs _activateTab for the in-place
 *     switch (the existing flow).
 * The ``data-href`` attribute stays on the button as a hint for
 * developers / a11y tools but is not honoured by the browser itself.
 * The new tab lands on ``dashboard/#<tab>`` and the boot code below
 * reads the hash to activate the requested tab. */
function _isNewTabClick(ev) {
  /* Middle mouse button = ev.button === 1. Cmd (mac) = metaKey.
   * Ctrl (win/linux) = ctrlKey. Shift opens in a new window on most
   * browsers; treat it the same (user intent = "not in place"). */
  return ev.button === 1 || ev.metaKey || ev.ctrlKey || ev.shiftKey;
}

document.querySelectorAll(".tab-btn").forEach(function (btn) {
  /* Install an anchor-style href so the browser exposes the standard
   * "Open in new tab" / "Open in new window" context menu entries, and
   * so middle-click raises a new background tab by default. Buttons
   * themselves don't honour href (they're not anchors), but modifier-
   * key clicks still get our custom handler below which opens a fresh
   * tab via window.open. The href stays consistent with the hash-route
   * the new tab's boot code looks for. */
  var tab = btn.getAttribute("data-tab") || "";
  if (tab && !btn.hasAttribute("data-href")) {
    btn.setAttribute("data-href", "#" + tab);
  }
  /* Middle-click (auxclick) on a <button> fires regardless of href. */
  btn.addEventListener("auxclick", function (ev) {
    /* Middle button only (1). Right-click (2) lets the browser show
     * its own context menu. */
    if (ev.button !== 1) return;
    ev.preventDefault();
    var t = btn.getAttribute("data-tab");
    if (!t) return;
    try {
      window.open(window.location.pathname + "#" + t, "_blank");
    } catch (_) {}
  });
  btn.addEventListener("click", function (ev) {
    var t = btn.getAttribute("data-tab");
    if (!t) return;
    if (_isNewTabClick(ev)) {
      /* Cmd/Ctrl/Shift click — open a new tab/window. Use a blank
       * target so each click spawns its own surface; suppress the
       * in-place switch. */
      ev.preventDefault();
      try {
        window.open(window.location.pathname + "#" + t, "_blank");
      } catch (_) {}
      return;
    }
    if (t === activeTab) return;
    _activateTab(t);
  });
});

/* Restore last open tab across reloads.
 *
 * Step 3a (Overview promotion): default landing is the Overview tab
 * (internal id "activity"). If localStorage has a remembered tab AND
 * its button still exists in the DOM, honor it — otherwise fall back
 * to Overview. Activating Overview on boot is what makes first paint
 * land there; we intentionally do NOT rely on inline display:none on
 * Chat surfaces — _activateTab("activity") hides them imperatively. */
(function () {
  try {
    /* msg#16116 Item 3: hash-based tab routing. When a cmd/middle-click
     * on a tab button opens a new browser tab, the fresh tab loads the
     * dashboard with ``#<tab>`` as the URL fragment. Honor that hash
     * FIRST — it reflects the explicit "open this view in a new tab"
     * intent. Fall back to localStorage (in-place session continuity)
     * and finally Overview. */
    var hash = "";
    try {
      hash = (window.location.hash || "").replace(/^#/, "");
    } catch (_) {
      hash = "";
    }
    var last = localStorage.getItem("orochi_active_tab");
    /* Step 3c: the top-level Terminal tab has been removed (terminal
     * preview now lives only inside the agent-detail pane's SSH action).
     * Users who left their last session on "terminal" fall through. */
    if (last === "terminal") {
      last = null;
    }
    if (hash === "terminal") {
      hash = "";
    }
    /* msg#16337: Overview loses its Viz/List toggle — Overview is
     * Viz-only, and the List surface moves to the dedicated Agents
     * tab. If the user's last session had activity + list subview
     * selected, redirect their next boot to the Agents tab so they
     * land on the list they were looking at (not an empty graph).
     * Graph/topology users on activity land on Overview as before.
     * Consumes the legacy orochi.overviewView key one time and
     * rewrites it to "topology" to match the new UI contract. */
    if (last === "activity") {
      try {
        var _legacyOverviewView = localStorage.getItem("orochi.overviewView");
        if (_legacyOverviewView === "list" || _legacyOverviewView === "tiled") {
          last = "agents-tab";
          localStorage.setItem("orochi.overviewView", "topology");
          localStorage.setItem("orochi_active_tab", "agents-tab");
        }
      } catch (_) {}
    }
    var target = hash || last || "activity";
    /* If the requested tab no longer has a DOM button, fall back to
     * Overview ("activity"). */
    var btn = document.querySelector('.tab-btn[data-tab="' + target + '"]');
    if (!btn) {
      target = "activity";
      btn = document.querySelector('.tab-btn[data-tab="' + target + '"]');
    }
    if (btn) _activateTab(target);
  } catch (_) {
    /* Even if localStorage is unavailable (private mode / quota), we
     * still want to land on Overview. */
    try {
      _activateTab("activity");
    } catch (__) {}
  }
})();

/* Collapsible sidebar sections (#321 fix: use data-section for stable keys) */
(function () {
  /* Derive a stable key for a collapsible heading.
   * Prefer data-section attribute; fall back to textContent for legacy compat. */
  function sectionKey(h2) {
    return h2.getAttribute("data-section") || h2.textContent.trim();
  }

  /* Restore collapsed state on initial load */
  function applySavedState() {
    var saved = {};
    try {
      saved = JSON.parse(localStorage.getItem("orochi_collapsed") || "{}");
    } catch (e) {
      /* ignore */
    }
    document.querySelectorAll(".collapsible-heading").forEach(function (h2) {
      var key = sectionKey(h2);
      var section = h2.nextElementSibling;
      if (saved[key]) {
        h2.classList.add("collapsed");
        if (section) section.classList.add("collapsed");
      }
    });
  }
  applySavedState();
  /* The previous implementation used a MutationObserver on the sidebar to
   * re-apply collapsed state whenever the DOM changed. This caused a bug
   * (#321) where dynamic count updates in headings changed the textContent
   * key, making expand/collapse state unreliable. With stable data-section
   * keys the observer is no longer needed — applySavedState runs once on
   * load and the click handler manages state from there. */

  /* Event delegation: works for dynamically inserted .collapsible-heading */
  document.addEventListener("click", function (e) {
    var h2 = e.target.closest(".collapsible-heading");
    if (!h2) return;
    /* Ignore clicks on interactive children (e.g. the new-DM "+" button) */
    if (e.target.closest("button")) return;
    var key = sectionKey(h2);
    var section = h2.nextElementSibling;
    var isCollapsed = h2.classList.toggle("collapsed");
    if (section) section.classList.toggle("collapsed", isCollapsed);
    try {
      var state = JSON.parse(localStorage.getItem("orochi_collapsed") || "{}");
      if (isCollapsed) {
        state[key] = true;
      } else {
        delete state[key];
      }
      localStorage.setItem("orochi_collapsed", JSON.stringify(state));
    } catch (err) {
      /* ignore */
    }
  });
})();

/* Mobile sidebar hamburger toggle */
(function () {
  var toggle = document.getElementById("sidebar-toggle");
  var sidebar = document.getElementById("sidebar");
  if (!toggle || !sidebar) return;
  var backdrop = document.createElement("div");
  backdrop.className = "sidebar-backdrop";
  document.body.appendChild(backdrop);
  function openSidebar() {
    sidebar.classList.add("open");
    toggle.classList.add("open");
    toggle.innerHTML = "&#10005;";
    backdrop.classList.add("visible");
  }
  function closeSidebar() {
    sidebar.classList.remove("open");
    toggle.classList.remove("open");
    toggle.innerHTML = "&#9776;";
    backdrop.classList.remove("visible");
  }
  toggle.addEventListener("click", function () {
    if (sidebar.classList.contains("open")) {
      closeSidebar();
    } else {
      openSidebar();
    }
  });
  backdrop.addEventListener("click", closeSidebar);
  var chEl = document.getElementById("channels");
  if (chEl) {
    chEl.addEventListener("click", function (e) {
      if (e.target.closest(".channel-item") && window.innerWidth <= 600) {
        closeSidebar();
      }
    });
  }

  /* Swipe-right from left edge to open sidebar on iPhone — msg#9393 */
  var _swipeStartX = null;
  var _swipeStartY = null;
  document.addEventListener(
    "touchstart",
    function (e) {
      _swipeStartX = e.touches[0].clientX;
      _swipeStartY = e.touches[0].clientY;
    },
    { passive: true },
  );
  document.addEventListener(
    "touchend",
    function (e) {
      if (_swipeStartX === null) return;
      var dx = e.changedTouches[0].clientX - _swipeStartX;
      var dy = e.changedTouches[0].clientY - _swipeStartY;
      var absDx = Math.abs(dx);
      var absDy = Math.abs(dy);
      /* Only handle horizontal swipes (more x-movement than y) */
      if (absDx < 40 || absDy > absDx) {
        _swipeStartX = null;
        return;
      }
      if (dx > 0 && _swipeStartX < 40) {
        /* Right swipe from left edge → open sidebar */
        openSidebar();
      } else if (dx < 0 && sidebar.classList.contains("open")) {
        /* Left swipe anywhere → close sidebar */
        closeSidebar();
      }
      _swipeStartX = null;
    },
    { passive: true },
  );
})();
