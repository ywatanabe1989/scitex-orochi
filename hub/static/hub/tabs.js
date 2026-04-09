/* Tab switching, collapsible sections, mobile sidebar */
/* globals: activeTab, fetchTodoList, renderAgentsTab, renderResourcesTab,
   fetchWorkspaces */

var activeTab = "chat";

document.querySelectorAll(".tab-btn").forEach(function (btn) {
  btn.addEventListener("click", function () {
    var tab = btn.getAttribute("data-tab");
    if (tab === activeTab) return;
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
    var settingsView = document.getElementById("settings-view");
    messagesEl.style.display = "none";
    inputBar.style.display = "none";
    todoView.style.display = "none";
    resourcesView.style.display = "none";
    agentsTabView.style.display = "none";
    workspacesView.style.display = "none";
    if (settingsView) settingsView.style.display = "none";
    if (tab === "chat") {
      messagesEl.style.display = "";
      inputBar.style.display = "";
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
    } else if (tab === "settings" && settingsView) {
      settingsView.style.display = "block";
      settingsView.style.flex = "1";
      fetchSettings();
    }
  });
});

/* Collapsible sidebar sections */
(function () {
  var saved = {};
  try {
    saved = JSON.parse(localStorage.getItem("orochi_collapsed") || "{}");
  } catch (e) {
    /* ignore */
  }
  document.querySelectorAll(".collapsible-heading").forEach(function (h2) {
    var key = h2.textContent.trim();
    var section = h2.nextElementSibling;
    if (saved[key]) {
      h2.classList.add("collapsed");
      if (section) section.classList.add("collapsed");
    }
    h2.addEventListener("click", function () {
      var isCollapsed = h2.classList.toggle("collapsed");
      if (section) section.classList.toggle("collapsed", isCollapsed);
      try {
        var state = JSON.parse(
          localStorage.getItem("orochi_collapsed") || "{}",
        );
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
})();
