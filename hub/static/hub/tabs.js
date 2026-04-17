/* Tab switching, collapsible sections, mobile sidebar */
/* globals: activeTab, fetchTodoList, renderAgentsTab, renderResourcesTab,
   fetchWorkspaces */

var activeTab = "chat";

function _activateTab(tab) {
  activeTab = tab;
  document.querySelectorAll(".tab-btn").forEach(function (b) {
    b.classList.toggle("active", b.getAttribute("data-tab") === tab);
  });
  var messagesEl = document.getElementById("messages");
  var inputBar = document.querySelector(".input-bar");
  var todoView = document.getElementById("todo-view");
  var resourcesView = document.getElementById("resources-view");
  var agentsTabView = document.getElementById("agents-tab-view");
  var workspacesView = document.getElementById("workspaces-view");
  var activityView = document.getElementById("activity-view");
  var filesView = document.getElementById("files-view");
  var releasesView = document.getElementById("releases-view");
  var settingsView = document.getElementById("settings-view");
  var vizView = document.getElementById("viz-view");
  messagesEl.style.display = "none";
  inputBar.style.display = "none";
  todoView.style.display = "none";
  resourcesView.style.display = "none";
  agentsTabView.style.display = "none";
  workspacesView.style.display = "none";
  if (activityView) activityView.style.display = "none";
  if (filesView) filesView.style.display = "none";
  if (releasesView) releasesView.style.display = "none";
  if (settingsView) settingsView.style.display = "none";
  if (vizView) vizView.style.display = "none";
  if (tab !== "viz" && typeof stopVizTab === "function") stopVizTab();
  if (tab === "chat") {
    messagesEl.style.display = "";
    inputBar.style.display = "";
    /* Always default-focus the compose input when the chat tab is shown.
     * Per ywatanabe spec (msg 5470, 2026-04-12): the compose textarea is
     * the primary action target on the chat tab, so the user should never
     * have to click into it manually after switching tabs or reloading.
     * Defer with rAF so the layout has settled (display:'' just changed). */
    requestAnimationFrame(function () {
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
      activityView.style.display = "block";
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
  } else if (tab === "settings" && settingsView) {
    settingsView.style.display = "block";
    settingsView.style.flex = "1";
    fetchSettings();
  } else if (tab === "viz") {
    if (vizView) {
      vizView.style.display = "block";
      vizView.style.flex = "1";
    }
    if (typeof renderVizTab === "function") renderVizTab();
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

/* Restore last open tab across reloads */
(function () {
  try {
    var last = localStorage.getItem("orochi_active_tab");
    if (last && last !== "chat") {
      var btn = document.querySelector('.tab-btn[data-tab="' + last + '"]');
      if (btn) _activateTab(last);
    }
  } catch (_) {}
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
