/* Tab switching, collapsible sections, mobile sidebar */
/* globals: activeTab, fetchTodoList, renderAgentsTab, renderResourcesTab,
   fetchWorkspaces */

/* Default landing tab — the Overview tab (internal id "activity" — see
 * note below) is the leftmost tab and the first-load landing surface.
 * The internal id stays "activity" even though the user-visible label
 * reads "Overview"; renaming the id would churn every globalThis/SSE
 * key that keys off it (_overviewExpanded, etc.), and the directory
 * name `activity-tab/` is likewise left alone per Step 3 spec. */
var activeTab = "activity";

function _activateTab(tab) {
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

document.querySelectorAll(".tab-btn").forEach(function (btn) {
  btn.addEventListener("click", function () {
    var tab = btn.getAttribute("data-tab");
    if (tab === activeTab) return;
    _activateTab(tab);
  });
});

/* Restore last open tab across reloads.
 *
 * PR Step 3 (Overview promotion): default landing is the Overview tab
 * (internal id "activity"). If localStorage has a remembered tab AND
 * its button still exists in the DOM, honor it — otherwise fall back
 * to Overview. We activate Overview synchronously so first paint lands
 * there without flashing through Chat; the inline `activity` default
 * on the Overview tab-button plus activeTab="activity" above already
 * gets us 90% of the way, but we still run _activateTab to trigger
 * the poll start + render-hook side effects. */
(function () {
  try {
    var last = localStorage.getItem("orochi_active_tab");
    var target = last || "activity";
    /* If the remembered tab no longer has a DOM button (e.g. Terminal
     * was demoted in this PR), fall through to Overview. */
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
