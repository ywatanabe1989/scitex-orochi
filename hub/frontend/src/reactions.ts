// @ts-nocheck
// Migrated classic-script file. Types intentionally loose during
// the big-bang JS-to-TS bundle migration. Narrow later, per-file.
/* Reactions — emoji reactions on messages */
/* globals: apiUrl, orochiHeaders, userName */

var COMMON_EMOJI = ["\uD83D\uDC4D", "\u2764\uFE0F", "\uD83D\uDC40", "\uD83D\uDE04", "\uD83C\uDF89", "\uD83E\uDD14", "\u2705", "\u274C"];
/* 👍 ❤️ 👀 😄 🎉 🤔 ✅ ❌ */

var reactionPicker = null;

function closeReactionPicker() {
  if (reactionPicker && reactionPicker.parentNode) {
    reactionPicker.parentNode.removeChild(reactionPicker);
  }
  reactionPicker = null;
}

function openReactionPicker(btn, messageId) {
  closeReactionPicker();
  reactionPicker = document.createElement("div");
  reactionPicker.className = "reaction-picker";
  COMMON_EMOJI.forEach(function (emoji) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "reaction-picker-btn";
    b.textContent = emoji;
    b.addEventListener("click", function (e) {
      e.stopPropagation();
      toggleReaction(messageId, emoji);
      closeReactionPicker();
    });
    reactionPicker.appendChild(b);
  });
  var rect = btn.getBoundingClientRect();
  reactionPicker.style.position = "fixed";
  reactionPicker.style.top = (rect.bottom + 4) + "px";
  /* Clamp to viewport — the react button sits in the top-right of each
   * message, so anchoring to rect.left pushes the picker off the right
   * edge on narrow screens, which clipped all but the first emoji. */
  document.body.appendChild(reactionPicker);
  var pickerWidth = reactionPicker.offsetWidth || 260;
  var left = Math.max(8, Math.min(rect.right - pickerWidth, window.innerWidth - pickerWidth - 8));
  reactionPicker.style.left = left + "px";
  /* Close on outside click */
  setTimeout(function () {
    document.addEventListener("click", closeReactionPicker, { once: true });
  }, 0);
}

async function toggleReaction(messageId, emoji) {
  var container = document.querySelector('.msg-reactions[data-msg-id="' + messageId + '"]');
  var existing = container ? container.querySelector('[data-emoji="' + emoji + '"]') : null;
  var method = existing && existing.classList.contains("reacted-by-me") ? "DELETE" : "POST";
  try {
    await fetch(apiUrl("/api/reactions/"), {
      method: method,
      headers: orochiHeaders(),
      credentials: "same-origin",
      body: JSON.stringify({ message_id: messageId, emoji: emoji }),
    });
    /* Optimistic update — the WS broadcast will confirm/correct */
    fetchReactionsForMessage(messageId);
  } catch (e) {
    console.error("toggleReaction error:", e);
  }
}

async function fetchReactionsForMessage(messageId) {
  try {
    var res = await fetch(apiUrl("/api/reactions/?message_ids=" + messageId), {
      credentials: "same-origin",
    });
    if (!res.ok) return;
    var data = await res.json();
    renderReactionsForMessage(messageId, data[messageId] || {});
  } catch (e) {
    /* ignore */
  }
}

async function fetchReactionsForMessages(messageIds) {
  if (!messageIds || messageIds.length === 0) return;
  try {
    var res = await fetch(apiUrl("/api/reactions/?message_ids=" + messageIds.join(",")), {
      credentials: "same-origin",
    });
    if (!res.ok) return;
    var data = await res.json();
    messageIds.forEach(function (mid) {
      renderReactionsForMessage(mid, data[mid] || {});
    });
  } catch (e) {
    /* ignore */
  }
}

function renderReactionsForMessage(messageId, reactionsByEmoji) {
  var container = document.querySelector('.msg-reactions[data-msg-id="' + messageId + '"]');
  if (!container) return;
  /* Mirror appendMessage's focus guard — see todo#225.
   * WS reaction_update events fire on foreign reactions and mutate
   * innerHTML inside a descendant of #messages, which on mobile Safari
   * can blur the compose textarea. Save + restore focus/selection. */
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var emojis = Object.keys(reactionsByEmoji);
  if (emojis.length === 0) {
    container.innerHTML = "";
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (e) {}
    }
    return;
  }
  container.innerHTML = emojis.map(function (emoji) {
    var reactors = reactionsByEmoji[emoji];
    var count = reactors.length;
    var byMe = reactors.some(function (r) { return r.reactor === userName; });
    var title = reactors.map(function (r) { return r.reactor; }).join(", ");
    return (
      '<span class="reaction-pill' + (byMe ? ' reacted-by-me' : '') + '"' +
      ' data-emoji="' + emoji + '"' +
      ' title="' + title + '"' +
      ' onclick="toggleReaction(' + messageId + ',\'' + emoji + '\')">' +
      emoji + ' ' + count +
      '</span>'
    );
  }).join("");
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (e) {}
  }
}

/* Handle WS reaction_update events (wired from app.js handleMessage) */
function handleReactionUpdate(msg) {
  if (!msg || !msg.message_id) return;
  fetchReactionsForMessage(msg.message_id);
}
