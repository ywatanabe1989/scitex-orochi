/* Workspace Dropdown -- click workspace-selector to switch workspaces */
/* globals: escapeHtml, getWorkspaceIcon, apiUrl */

(function () {
  var selector = document.getElementById("workspace-selector");
  if (!selector) return;

  var dropdown = null;
  var isOpen = false;

  function close() {
    if (dropdown && dropdown.parentNode) {
      dropdown.parentNode.removeChild(dropdown);
    }
    dropdown = null;
    isOpen = false;
  }

  function open() {
    if (isOpen) {
      close();
      return;
    }
    isOpen = true;

    dropdown = document.createElement("div");
    dropdown.className = "ws-dropdown";
    dropdown.innerHTML = '<div class="ws-dropdown-loading">Loading...</div>';
    selector.parentNode.appendChild(dropdown);

    fetch(apiUrl("/api/workspaces"), { credentials: "same-origin" })
      .then(function (res) {
        if (!res.ok) throw new Error("fetch failed");
        return res.json();
      })
      .then(function (workspaces) {
        if (!dropdown) return;
        var currentName = window.__orochiWorkspace || "";
        var html = workspaces
          .map(function (ws) {
            var isActive = ws.name === currentName;
            var icon =
              typeof getWorkspaceIcon === "function"
                ? getWorkspaceIcon(ws.name, 18)
                : "";
            return (
              '<a class="ws-dropdown-item' +
              (isActive ? " active" : "") +
              '" href="' +
              escapeHtml(ws.url || "#") +
              '">' +
              '<span class="ws-dropdown-icon">' +
              icon +
              "</span>" +
              '<span class="ws-dropdown-name">' +
              escapeHtml(ws.name) +
              "</span>" +
              "</a>"
            );
          })
          .join("");

        html +=
          '<a class="ws-dropdown-item ws-dropdown-create" href="/workspace/new/">' +
          '<span class="ws-dropdown-icon">+</span>' +
          '<span class="ws-dropdown-name">Create New</span>' +
          "</a>";

        dropdown.innerHTML = html;
      })
      .catch(function () {
        if (dropdown) {
          dropdown.innerHTML =
            '<div class="ws-dropdown-loading">Failed to load</div>';
        }
      });
  }

  selector.addEventListener("click", function (e) {
    e.stopPropagation();
    open();
  });

  document.addEventListener("click", function (e) {
    if (isOpen && dropdown && !dropdown.contains(e.target)) {
      close();
    }
  });

  document.addEventListener("keydown", function (e) {
    if (isOpen && e.key === "Escape") {
      close();
    }
  });
})();
