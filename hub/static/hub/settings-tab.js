/* Settings tab — loads workspace settings inline via fetch */
/* globals: apiUrl, escapeHtml, csrfToken */

var settingsLoaded = false;

function fetchSettings() {
  if (settingsLoaded) return;
  var container = document.getElementById("settings-content");
  if (!container) return;

  fetch(apiUrl("/settings/"), { credentials: "same-origin" })
    .then(function (res) {
      return res.text();
    })
    .then(function (html) {
      /* Extract the main content from the settings page HTML */
      var parser = new DOMParser();
      var doc = parser.parseFromString(html, "text/html");
      var main =
        doc.querySelector(".settings-page") ||
        doc.querySelector("main") ||
        doc.querySelector(".container");
      if (main) {
        container.innerHTML = main.innerHTML;
      } else {
        /* Fallback: use body content between nav and footer */
        container.innerHTML = doc.body.innerHTML;
      }
      settingsLoaded = true;
      wireSettingsForms(container);
    })
    .catch(function () {
      container.innerHTML =
        '<p class="empty-notice">Failed to load settings.</p>';
    });
}

function wireSettingsForms(container) {
  /* Make all forms in the settings tab submit via AJAX */
  container.querySelectorAll("form").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var formData = new FormData(form);
      fetch(form.action || apiUrl("/settings/"), {
        method: "POST",
        credentials: "same-origin",
        body: formData,
      })
        .then(function (res) {
          if (res.redirected) {
            /* Workspace renamed or deleted — follow redirect */
            window.location.href = res.url;
            return;
          }
          /* Reload settings content */
          settingsLoaded = false;
          fetchSettings();
        })
        .catch(function () {
          alert("Action failed. Please try again.");
        });
    });
  });

  /* Wire delete confirmation input */
  var deleteInput = container.querySelector('input[name="confirm_name"]');
  var deleteBtn = container.querySelector("#delete-ws-btn, .delete-ws-btn");
  if (deleteInput && deleteBtn) {
    var wsName = window.__orochiWorkspaceName || "";
    deleteBtn.disabled = true;
    deleteInput.addEventListener("input", function () {
      deleteBtn.disabled = this.value !== wsName;
    });
  }
}

/* Hook into tab switching */
var origTabClick = null;
document.addEventListener("DOMContentLoaded", function () {
  var settingsBtn = document.querySelector('[data-tab="settings"]');
  if (settingsBtn) {
    settingsBtn.addEventListener("click", function () {
      fetchSettings();
    });
  }
});
