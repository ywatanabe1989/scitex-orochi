/* Emoji Picker for workspace icon selection */
/* globals: csrfToken, apiUrl, getWorkspaceIcon */

(function () {
  "use strict";

  var EMOJI_LIST = [
    /* animals */
    "\uD83D\uDC0D",
    "\uD83D\uDC09",
    "\uD83E\uDD89",
    "\uD83D\uDC3A",
    "\uD83E\uDD8A",
    "\uD83D\uDC3B",
    "\uD83D\uDC31",
    "\uD83D\uDC36",
    "\uD83D\uDC1D",
    "\uD83E\uDD8B",
    "\uD83D\uDC22",
    "\uD83D\uDC19",
    /* objects & tools */
    "\uD83D\uDE80",
    "\u2699\uFE0F",
    "\uD83D\uDD2C",
    "\uD83D\uDCBB",
    "\uD83D\uDCDA",
    "\uD83D\uDD2D",
    "\u26A1",
    "\uD83D\uDD25",
    "\uD83C\uDF1F",
    "\uD83C\uDF0A",
    "\uD83C\uDF0D",
    "\uD83C\uDF19",
    /* symbols & shapes */
    "\u2764\uFE0F",
    "\uD83D\uDC8E",
    "\uD83D\uDD36",
    "\uD83D\uDD35",
    "\uD83D\uDFE2",
    "\uD83D\uDFE3",
    "\uD83D\uDFE0",
    "\uD83D\uDD34",
    /* activities */
    "\uD83C\uDFAF",
    "\uD83C\uDFB5",
    "\uD83C\uDFA8",
    "\uD83C\uDFC6",
    "\uD83E\uDDE9",
    "\uD83C\uDFAE",
    "\u265F\uFE0F",
    "\uD83D\uDCA1",
    /* plants & nature */
    "\uD83C\uDF31",
    "\uD83C\uDF3F",
    "\uD83C\uDF35",
    "\uD83C\uDF38",
    "\uD83C\uDF3B",
    "\uD83C\uDF3A",
    "\uD83C\uDF32",
    "\uD83C\uDF43",
  ];

  var overlay = null;

  function createPicker(onSelect) {
    if (overlay) close();

    overlay = document.createElement("div");
    overlay.className = "emoji-picker-overlay";

    var picker = document.createElement("div");
    picker.className = "emoji-picker";

    var header = document.createElement("div");
    header.className = "emoji-picker-header";
    header.textContent = "Choose workspace icon";
    picker.appendChild(header);

    var grid = document.createElement("div");
    grid.className = "emoji-picker-grid";

    /* "Clear" button to remove custom icon */
    var clearBtn = document.createElement("button");
    clearBtn.className = "emoji-picker-btn emoji-picker-clear";
    clearBtn.textContent = "\u2715";
    clearBtn.title = "Remove custom icon";
    clearBtn.addEventListener("click", function () {
      onSelect("");
      close();
    });
    grid.appendChild(clearBtn);

    EMOJI_LIST.forEach(function (emoji) {
      var btn = document.createElement("button");
      btn.className = "emoji-picker-btn";
      btn.textContent = emoji;
      btn.addEventListener("click", function () {
        onSelect(emoji);
        close();
      });
      grid.appendChild(btn);
    });

    picker.appendChild(grid);
    overlay.appendChild(picker);

    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) close();
    });

    document.body.appendChild(overlay);
    requestAnimationFrame(function () {
      overlay.classList.add("visible");
    });
  }

  function close() {
    if (!overlay) return;
    overlay.classList.remove("visible");
    setTimeout(function () {
      if (overlay && overlay.parentNode) {
        overlay.parentNode.removeChild(overlay);
      }
      overlay = null;
    }, 150);
  }

  function postIcon(emoji) {
    var formData = new FormData();
    formData.append("action", "set_icon");
    formData.append("icon", emoji);

    fetch(apiUrl("/settings/"), {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
      body: formData,
    })
      .then(function (res) {
        if (!res.ok) {
          console.error("set_icon failed:", res.status);
          return;
        }
        /* Update global and all visible icons */
        window.__orochiWorkspaceIcon = emoji;
        updateVisibleIcons(emoji);
      })
      .catch(function (e) {
        console.error("set_icon error:", e);
      });
  }

  function updateVisibleIcons(emoji) {
    var wsName = window.__orochiWorkspaceName || "workspace";

    /* Sidebar icon slot */
    var wsIconSlot = document.getElementById("ws-icon-slot");
    if (wsIconSlot) {
      wsIconSlot.innerHTML = emoji
        ? '<span class="ws-emoji-icon">' + emoji + "</span>"
        : getWorkspaceIcon(wsName, 16);
    }

    /* Settings preview if visible */
    var preview = document.getElementById("ws-icon-preview");
    if (preview) {
      preview.innerHTML = emoji
        ? '<span class="ws-emoji-icon ws-emoji-icon-lg">' + emoji + "</span>"
        : getWorkspaceIcon(wsName, 64);
    }
  }

  /* Wire up sidebar icon click */
  function wireIconClick() {
    var wsIconSlot = document.getElementById("ws-icon-slot");
    if (wsIconSlot) {
      wsIconSlot.style.cursor = "pointer";
      wsIconSlot.title = "Click to change workspace icon";
      wsIconSlot.addEventListener("click", function (e) {
        e.stopPropagation();
        createPicker(function (emoji) {
          postIcon(emoji);
        });
      });
    }
  }

  /* Wire up settings preview click (for settings loaded via AJAX) */
  function wireSettingsIconClick() {
    var observer = new MutationObserver(function () {
      var preview = document.getElementById("ws-icon-preview");
      if (preview && !preview.dataset.emojiWired) {
        preview.dataset.emojiWired = "1";
        preview.style.cursor = "pointer";
        preview.title = "Click to change workspace icon";
        preview.addEventListener("click", function (e) {
          e.stopPropagation();
          createPicker(function (emoji) {
            postIcon(emoji);
          });
        });
      }
    });
    var settingsContent = document.getElementById("settings-content");
    if (settingsContent) {
      observer.observe(settingsContent, { childList: true, subtree: true });
    }
  }

  /* Initialize on DOMContentLoaded */
  document.addEventListener("DOMContentLoaded", function () {
    wireIconClick();
    wireSettingsIconClick();
  });

  /* Also wire immediately in case DOM is already ready */
  if (document.readyState !== "loading") {
    wireIconClick();
    wireSettingsIconClick();
  }

  /* Expose for external use */
  window.openEmojiPicker = createPicker;
  window.closeEmojiPicker = close;
})();
