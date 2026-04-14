/* Feed keyboard navigation — Slack-like message selection and shortcuts.
 *
 * When the user presses ↑ in an empty input, focus moves to the last
 * message. ↑/↓ navigate between messages. Shortcuts while a message
 * is focused:
 *   Enter / R  — open quick-reply to the focused message
 *   E          — emoji reaction picker (if implemented)
 *   Escape     — return focus to the input
 *
 * ywatanabe msg#10295 request.
 */
(function () {
  var _focused = null; /* currently focused .msg element */

  function _getAllMsgs() {
    return Array.from(document.querySelectorAll("#messages .msg"));
  }

  function _focusMsg(el) {
    if (!el) return;
    if (_focused) {
      _focused.classList.remove("msg-nav-focused");
      _focused.removeAttribute("tabindex");
    }
    _focused = el;
    el.classList.add("msg-nav-focused");
    el.setAttribute("tabindex", "-1");
    el.focus();
    /* Scroll into view without hijacking the page position too aggressively */
    el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    _showNavHint(el);
  }

  function _clearFocus() {
    if (_focused) {
      _focused.classList.remove("msg-nav-focused");
      _focused.removeAttribute("tabindex");
      _focused = null;
    }
    _hideNavHint();
    var inp = document.getElementById("msg-input");
    if (inp) inp.focus();
  }

  /* ── Nav hint bar ── */
  var _hint = null;
  function _showNavHint(el) {
    if (!_hint) {
      _hint = document.createElement("div");
      _hint.id = "feed-nav-hint";
      _hint.className = "feed-nav-hint";
      document.body.appendChild(_hint);
    }
    var msgId = el.getAttribute("data-msg-id");
    _hint.innerHTML =
      '<span class="fnh-keys">↑↓</span> navigate &nbsp;·&nbsp;' +
      '<span class="fnh-keys">Enter</span> reply &nbsp;·&nbsp;' +
      '<span class="fnh-keys">E</span> react &nbsp;·&nbsp;' +
      '<span class="fnh-keys">Esc</span> back to input';
    _hint.style.display = "flex";
  }
  function _hideNavHint() {
    if (_hint) _hint.style.display = "none";
  }

  /* ── Input keydown: ↑ in empty input → enter nav mode ── */
  document.addEventListener("DOMContentLoaded", function () {
    var inp = document.getElementById("msg-input");
    if (!inp) return;

    inp.addEventListener("keydown", function (e) {
      if (e.key === "ArrowUp" && inp.value === "") {
        e.preventDefault();
        var msgs = _getAllMsgs();
        if (msgs.length > 0) _focusMsg(msgs[msgs.length - 1]);
      }
    });
  });

  /* ── Global keydown: nav between messages while one is focused ── */
  document.addEventListener("keydown", function (e) {
    if (!_focused) return;

    if (e.key === "Escape") {
      e.preventDefault();
      _clearFocus();
      return;
    }

    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      var msgs = _getAllMsgs();
      var idx = msgs.indexOf(_focused);
      var next = e.key === "ArrowDown" ? msgs[idx + 1] : msgs[idx - 1];
      if (next) {
        _focusMsg(next);
      } else if (e.key === "ArrowDown") {
        /* Past last message → return to input */
        _clearFocus();
      }
      return;
    }

    if (e.key === "Enter" || e.key === "r" || e.key === "R") {
      e.preventDefault();
      var msgId = _focused.getAttribute("data-msg-id");
      if (msgId && typeof window.openReplyPanel === "function") {
        window.openReplyPanel(parseInt(msgId, 10));
      } else {
        /* Fallback: click the reply button in the focused message */
        var replyBtn = _focused.querySelector(".reply-btn, .action-reply, [data-action=\"reply\"]");
        if (replyBtn) replyBtn.click();
      }
      _clearFocus();
      return;
    }

    if (e.key === "e" || e.key === "E") {
      e.preventDefault();
      /* Trigger the emoji reaction picker for the focused message */
      var emojiBtn = _focused.querySelector(".emoji-btn, .action-react, [data-action=\"react\"], .msg-emoji-btn");
      if (emojiBtn) emojiBtn.click();
      return;
    }
  });

  /* ── Click outside feed clears nav focus ── */
  document.addEventListener("mousedown", function (e) {
    if (!_focused) return;
    var feed = document.getElementById("messages");
    if (feed && !feed.contains(e.target)) _clearFocus();
  });
})();
