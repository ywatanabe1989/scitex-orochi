// @ts-nocheck
// Migrated classic-script file. Types intentionally loose during
// the big-bang JS-to-TS bundle migration. Narrow later, per-file.
/* --- Edit / Delete message support --- */

function startEditMessage(msgId) {
  var el = document.querySelector('.msg[data-msg-id="' + msgId + '"]');
  if (!el) return;
  var contentEl = el.querySelector(".content");
  if (!contentEl) return;
  /* Prevent double-editing */
  if (el.querySelector(".msg-edit-input")) return;

  /* Extract plain text from rendered HTML (reverse of escapeHtml + <br>) */
  var currentText = contentEl.innerText || contentEl.textContent || "";

  /* Hide content and action buttons while editing */
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  contentEl.style.display = "none";
  var editContainer = document.createElement("div");
  editContainer.className = "msg-edit-container";
  editContainer.innerHTML =
    '<textarea class="msg-edit-input" rows="2">' +
    escapeHtml(currentText) +
    "</textarea>" +
    '<div class="msg-edit-actions">' +
    '<button class="msg-edit-save" type="button">Save</button>' +
    '<button class="msg-edit-cancel" type="button">Cancel</button>' +
    "</div>";
  contentEl.parentNode.insertBefore(editContainer, contentEl.nextSibling);
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }

  var textarea = editContainer.querySelector(".msg-edit-input");
  textarea.focus();
  textarea.setSelectionRange(textarea.value.length, textarea.value.length);

  /* Auto-resize */
  textarea.style.height = "auto";
  textarea.style.height = Math.min(textarea.scrollHeight, 200) + "px";

  editContainer
    .querySelector(".msg-edit-save")
    .addEventListener("click", function () {
      saveEditMessage(msgId, textarea.value);
    });
  editContainer
    .querySelector(".msg-edit-cancel")
    .addEventListener("click", function () {
      cancelEditMessage(msgId);
    });
  textarea.addEventListener("keydown", function (e) {
    /* todo#332: Shift+Enter and Alt+Enter both insert a newline */
    if (e.key === "Enter" && !e.shiftKey && !e.altKey) {
      e.preventDefault();
      saveEditMessage(msgId, textarea.value);
    }
    if (e.key === "Escape") {
      cancelEditMessage(msgId);
    }
  });
}

function saveEditMessage(msgId, newText) {
  newText = (newText || "").trim();
  if (!newText) return;
  fetch(apiUrl("/api/messages/" + msgId + "/"), {
    method: "PATCH",
    headers: orochiHeaders(),
    credentials: "same-origin",
    body: JSON.stringify({ text: newText }),
  })
    .then(function (res) {
      if (!res.ok) {
        res.json().then(function (d) {
          console.error("Edit failed:", d.error || res.status);
        });
      }
      /* The WebSocket broadcast will update the UI */
    })
    .catch(function (e) {
      console.error("Edit error:", e);
    });
  /* Immediately close the editor for snappy UX */
  cancelEditMessage(msgId);
}

function cancelEditMessage(msgId) {
  var el = document.querySelector('.msg[data-msg-id="' + msgId + '"]');
  if (!el) return;
  var editContainer = el.querySelector(".msg-edit-container");
  if (editContainer) editContainer.remove();
  var contentEl = el.querySelector(".content");
  if (contentEl) contentEl.style.display = "";
}

function deleteMessage(msgId) {
  fetch(apiUrl("/api/messages/" + msgId + "/"), {
    method: "DELETE",
    headers: orochiHeaders(),
    credentials: "same-origin",
  })
    .then(function (res) {
      if (!res.ok) {
        res.json().then(function (d) {
          console.error("Delete failed:", d.error || res.status);
        });
      }
      /* The WebSocket broadcast will remove it from the UI */
    })
    .catch(function (e) {
      console.error("Delete error:", e);
    });
}

function handleMessageEdit(event) {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var el = document.querySelector(
    '.msg[data-msg-id="' + event.message_id + '"]',
  );
  if (!el) return;
  var contentEl = el.querySelector(".content");
  if (contentEl) {
    contentEl.innerHTML = escapeHtml(event.text).replace(/\n/g, "<br>");
  }
  /* Add or update the (edited) tag */
  var header = el.querySelector(".msg-header");
  if (header && !header.querySelector(".msg-edited-tag")) {
    var tag = document.createElement("span");
    tag.className = "msg-edited-tag";
    tag.title = event.edited_at
      ? "Edited " + timeAgo(event.edited_at)
      : "Edited";
    tag.textContent = "(edited)";
    header.appendChild(tag);
  }
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
}

function handleMessageDelete(event) {
  var el = document.querySelector(
    '.msg[data-msg-id="' + event.message_id + '"]',
  );
  if (el) {
    el.classList.add("msg-deleted");
    setTimeout(function () {
      el.remove();
    }, 300);
  }
}

/* Timestamps are now absolute (YYYY-MM-DD HH:mm:ss), no periodic refresh needed */

/* --- Long-press context menu (mobile) ---
 * On touch devices, holding a finger on a message for ~500ms opens a
 * floating action menu with Reply / React / Edit / Delete / Copy.
 * Desktop continues to use the existing hover buttons.
 *
 * Implementation notes:
 *   - Uses event delegation on #messages so it picks up dynamically
 *     appended .msg elements without per-message wiring.
 *   - Cancels if the finger moves >10px (treat as scroll) or lifts early.
 *   - Suppresses the synthetic click that follows touchend so taps on
 *     links/buttons inside the message don't fire after a long press.
 *   - Skips when the touch target is an interactive control (textarea,
 *     button, input, link, image attachment).
 */
(function () {
  var LONG_PRESS_MS = 500;
  var MOVE_TOLERANCE = 10;
  var pressTimer = null;
  var pressTarget = null;
  var startX = 0;
  var startY = 0;
  var didLongPress = false;
  var openMenu = null;

  function isTouchDevice() {
    return (
      "ontouchstart" in window ||
      (navigator.maxTouchPoints && navigator.maxTouchPoints > 0)
    );
  }

  function isInteractiveTarget(node) {
    while (node && node !== document.body) {
      var tag = node.tagName;
      if (
        tag === "TEXTAREA" ||
        tag === "BUTTON" ||
        tag === "INPUT" ||
        tag === "A" ||
        tag === "SELECT"
      ) {
        return true;
      }
      if (node.classList && node.classList.contains("msg-edit-container")) {
        return true;
      }
      node = node.parentNode;
    }
    return false;
  }

  function closeLongPressMenu() {
    if (openMenu && openMenu.parentNode) {
      openMenu.parentNode.removeChild(openMenu);
    }
    openMenu = null;
    document.removeEventListener("touchstart", _outsideHandler, true);
    document.removeEventListener("mousedown", _outsideHandler, true);
  }

  function _outsideHandler(e) {
    if (openMenu && !openMenu.contains(e.target)) {
      closeLongPressMenu();
    }
  }

  function getMessageMeta(msgEl) {
    var idStr = msgEl.getAttribute("data-msg-id");
    var msgId = idStr ? parseInt(idStr, 10) : null;
    var senderEl = msgEl.querySelector(".sender");
    var sender = senderEl ? senderEl.textContent.trim() : "";
    var contentEl = msgEl.querySelector(".content");
    var text = contentEl
      ? contentEl.innerText || contentEl.textContent || ""
      : "";
    var isOwn =
      typeof userName !== "undefined" &&
      sender &&
      (sender === userName || sender === cleanAgentName(userName));
    return { msgId: msgId, sender: sender, text: text, isOwn: isOwn };
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).catch(function () {});
      return;
    }
    /* Fallback for older mobile Safari */
    try {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    } catch (_) {}
  }

  function showLongPressMenu(msgEl, x, y) {
    closeLongPressMenu();
    var meta = getMessageMeta(msgEl);
    if (!meta.msgId) return;

    var menu = document.createElement("div");
    menu.className = "long-press-menu";

    var actions = [
      {
        label: "Reply",
        icon: "\uD83D\uDCAC",
        run: function () {
          if (typeof openThreadForMessage === "function") {
            openThreadForMessage(meta.msgId);
          }
        },
      },
      {
        label: "React",
        icon: "\u263A",
        run: function () {
          var btn = msgEl.querySelector(".msg-react-btn");
          if (typeof openReactionPicker === "function") {
            openReactionPicker(btn || msgEl, meta.msgId);
          }
        },
      },
    ];
    if (meta.isOwn) {
      actions.push({
        label: "Edit",
        icon: "\u270F\uFE0F",
        run: function () {
          if (typeof startEditMessage === "function") {
            startEditMessage(meta.msgId);
          }
        },
      });
      actions.push({
        label: "Delete",
        icon: "\uD83D\uDDD1\uFE0F",
        cls: "danger",
        run: function () {
          if (typeof deleteMessage === "function") {
            deleteMessage(meta.msgId);
          }
        },
      });
    }
    actions.push({
      label: "Copy text",
      icon: "\uD83D\uDCCB",
      run: function () {
        copyText(meta.text);
      },
    });

    actions.forEach(function (a) {
      var item = document.createElement("button");
      item.type = "button";
      item.className = "long-press-item" + (a.cls ? " " + a.cls : "");
      item.innerHTML =
        '<span class="long-press-icon">' +
        a.icon +
        '</span><span class="long-press-label">' +
        a.label +
        "</span>";
      item.addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        closeLongPressMenu();
        try {
          a.run();
        } catch (err) {
          console.error("long-press action failed:", err);
        }
      });
      menu.appendChild(item);
    });

    /* Position: anchor near touch point but clamp to viewport */
    document.body.appendChild(menu);
    var rect = menu.getBoundingClientRect();
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var left = Math.min(Math.max(8, x - rect.width / 2), vw - rect.width - 8);
    var top = y + 12;
    if (top + rect.height > vh - 8) {
      top = Math.max(8, y - rect.height - 12);
    }
    menu.style.left = left + "px";
    menu.style.top = top + "px";

    openMenu = menu;
    /* Defer outside-click binding so the originating touch doesn't close it */
    setTimeout(function () {
      document.addEventListener("touchstart", _outsideHandler, true);
      document.addEventListener("mousedown", _outsideHandler, true);
    }, 0);

    /* Haptic hint where supported */
    if (navigator.vibrate) {
      try {
        navigator.vibrate(15);
      } catch (_) {}
    }
  }

  function clearPressTimer() {
    if (pressTimer) {
      clearTimeout(pressTimer);
      pressTimer = null;
    }
    pressTarget = null;
  }

  function onTouchStart(e) {
    if (e.touches.length !== 1) return;
    var t = e.target;
    if (isInteractiveTarget(t)) return;
    var msgEl = t.closest && t.closest(".msg");
    if (!msgEl || msgEl.classList.contains("msg-system")) return;
    if (!msgEl.getAttribute("data-msg-id")) return;

    didLongPress = false;
    pressTarget = msgEl;
    var touch = e.touches[0];
    startX = touch.clientX;
    startY = touch.clientY;

    pressTimer = setTimeout(function () {
      didLongPress = true;
      showLongPressMenu(msgEl, startX, startY);
    }, LONG_PRESS_MS);
  }

  function onTouchMove(e) {
    if (!pressTimer) return;
    var touch = e.touches[0];
    if (!touch) return;
    var dx = Math.abs(touch.clientX - startX);
    var dy = Math.abs(touch.clientY - startY);
    if (dx > MOVE_TOLERANCE || dy > MOVE_TOLERANCE) {
      clearPressTimer();
    }
  }

  function onTouchEnd() {
    clearPressTimer();
  }

  function onTouchCancel() {
    clearPressTimer();
  }

  /* Suppress the synthetic click that follows a long-press touch sequence
   * so the underlying message links/buttons don't fire after the menu opens. */
  function onClickCapture(e) {
    if (didLongPress) {
      didLongPress = false;
      e.preventDefault();
      e.stopPropagation();
    }
  }

  function init() {
    if (!isTouchDevice()) return;
    var container = document.getElementById("messages");
    if (!container) return;
    container.addEventListener("touchstart", onTouchStart, { passive: true });
    container.addEventListener("touchmove", onTouchMove, { passive: true });
    container.addEventListener("touchend", onTouchEnd, { passive: true });
    container.addEventListener("touchcancel", onTouchCancel, { passive: true });
    container.addEventListener("click", onClickCapture, true);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

/* Channel name click → switch channel (#211) */
document.addEventListener("click", function (e) {
  var link = e.target.closest(".channel-link");
  if (!link) return;
  e.preventDefault();
  var ch = link.getAttribute("data-channel");
  if (!ch) return;
  if (typeof currentChannel !== "undefined") {
    if (currentChannel === ch) {
      if (typeof setCurrentChannel === "function") setCurrentChannel(null);
      else currentChannel = null;
      if (typeof loadHistory === "function") loadHistory();
    } else {
      if (typeof setCurrentChannel === "function") setCurrentChannel(ch);
      else currentChannel = ch;
      if (typeof loadChannelHistory === "function") loadChannelHistory(ch);
    }
    if (typeof addTag === "function") addTag("channel", ch);
    if (typeof fetchStats === "function") fetchStats();
  }
});
