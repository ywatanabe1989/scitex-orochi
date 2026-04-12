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
      var msgInput = document.getElementById("msg-input");
      var inputHasFocus = msgInput && document.activeElement === msgInput;
      var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
      var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
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
      if (inputHasFocus && document.activeElement !== msgInput) {
        msgInput.focus();
        try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
      }
    })
    .catch(function () {
      var msgInput = document.getElementById("msg-input");
      var inputHasFocus = msgInput && document.activeElement === msgInput;
      var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
      var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
      container.innerHTML =
        '<p class="empty-notice">Failed to load settings.</p>';
      if (inputHasFocus && document.activeElement !== msgInput) {
        msgInput.focus();
        try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
      }
    });
}

function wireSettingsModeTabs(container) {
  /* User/Workspace mode pane toggle — must run after AJAX load because the
   * panes do not exist at DOMContentLoaded. */
  var btns = container.querySelectorAll(".settings-mode-btn");
  var panes = container.querySelectorAll(".settings-mode-pane");
  if (!btns.length || !panes.length) return;
  btns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var mode = btn.getAttribute("data-mode");
      btns.forEach(function (b) {
        b.classList.toggle("active", b === btn);
      });
      panes.forEach(function (p) {
        p.style.display = p.getAttribute("data-mode") === mode ? "" : "none";
      });
    });
  });
}

function _wireSettingsIconPicker(container) {
  /* Workspace icon emoji picker — clicking the preview opens a simple
   * native prompt (kept dependency-free) and POSTs the selection via the
   * hidden form which Django handles with action=set_icon. */
  var preview = container.querySelector(".ws-icon-clickable, #ws-icon-preview");
  var iconInput = container.querySelector("#icon-input");
  var form = container.querySelector(".settings-form-icon");
  if (!preview || !iconInput || !form) return;
  preview.addEventListener("click", function () {
    var emoji = window.prompt(
      "Enter a single emoji (or leave blank to clear):",
      "",
    );
    if (emoji === null) return;
    iconInput.value = emoji.trim();
    form.submit();
  });
}

function wireSettingsForms(container) {
  wireSettingsModeTabs(container);
  _wireSettingsIconPicker(container);
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
