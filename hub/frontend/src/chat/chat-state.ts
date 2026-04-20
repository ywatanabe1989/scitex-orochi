// @ts-nocheck
/* Chat module -- message display, history, filtering */
/* globals: escapeHtml, getAgentColor, timeAgo, cachedAgentNames, userName,
   currentChannel, knownMessageKeys, messageKey, sendOrochiMessage,
   updateResourcePanel, token, apiUrl */

/* Visual-effects state (see hub/static/hub/effects.css).
 *
 * `_initialLoadComplete` flips true after the first history-load pass
 * finishes. Until then, appendMessage skips the `.msg-arrived` fade-in so
 * historically-loaded messages don't animate on initial render. After the
 * flag flips, only messages arriving AFTER page load (via WebSocket) get
 * the fade. It stays true across channel switches — subsequent
 * loadChannelHistory rebuilds are suppressed by an inline `_isLoadingHistory`
 * guard around the loop instead. */
var _initialLoadComplete = false;
var _isLoadingHistory = false;

/* Regex matcher for @<userName> and @me. Rebuilt lazily because `userName`
 * isn't defined until app.js has parsed its var declaration. */
var _mentionRegexCache = null;
function _mentionRegex() {
  if (_mentionRegexCache) return _mentionRegexCache;
  var name = (typeof userName !== "undefined" && userName) || "";
  var escName = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  var pattern = "(^|[^\\w])@(me" + (escName ? "|" + escName : "") + ")\\b";
  _mentionRegexCache = new RegExp(pattern, "i");
  return _mentionRegexCache;
}

/* Briefly pulse a sidebar row (channel or DM). `variant` = "dm" (teal)
 * or "mention" (red). Class is auto-removed on animationend so it can
 * re-fire next arrival. */
function _pulseSidebarRow(channel, variant) {
  if (!channel) return;
  var safe = channel.replace(/"/g, '\\"');
  var rows = document.querySelectorAll(
    '.dm-item[data-channel="' +
      safe +
      '"], .channel-item[data-channel="' +
      safe +
      '"]',
  );
  var cls = variant === "mention" ? "ch-pulse-mention" : "dm-pulse";
  rows.forEach(function (row) {
    row.classList.remove(cls);
    void row.offsetWidth;
    row.classList.add(cls);
    var done = function () {
      row.classList.remove(cls);
      row.removeEventListener("animationend", done);
    };
    row.addEventListener("animationend", done);
    if (variant === "mention") {
      var badge = row.querySelector(".unread-badge");
      if (badge) {
        badge.classList.remove("badge-shake");
        void badge.offsetWidth;
        badge.classList.add("badge-shake");
        var badgeDone = function () {
          badge.classList.remove("badge-shake");
          badge.removeEventListener("animationend", badgeDone);
        };
        badge.addEventListener("animationend", badgeDone);
      }
    }
  });
}
window._pulseSidebarRow = _pulseSidebarRow;

/* Chat sticky filter bar — client-side text filter over visible messages
 * in the current channel. Resets on channel switch. */
var _chatFilterQuery = "";
var _chatFilterDebounce = null;
function _chatFilterApplyNow(q) {
  _chatFilterQuery = (q || "").trim().toLowerCase();
  var container = document.getElementById("messages");
  if (!container) return;
  var rows = container.querySelectorAll(".message");
  if (!_chatFilterQuery) {
    rows.forEach(function (el) {
      el.classList.remove("chat-filter-miss");
      el.classList.remove("chat-filter-hit");
    });
    return;
  }
  for (var i = 0; i < rows.length; i++) {
    var el = rows[i];
    var txt = (el.textContent || "").toLowerCase();
    if (txt.indexOf(_chatFilterQuery) !== -1) {
      el.classList.add("chat-filter-hit");
      el.classList.remove("chat-filter-miss");
    } else {
      el.classList.add("chat-filter-miss");
      el.classList.remove("chat-filter-hit");
    }
  }
}
function chatFilterApply(q) {
  if (_chatFilterDebounce) clearTimeout(_chatFilterDebounce);
  _chatFilterDebounce = setTimeout(function () {
    _chatFilterDebounce = null;
    _chatFilterApplyNow(q);
  }, 100);
}
function chatFilterReset() {
  if (_chatFilterDebounce) {
    clearTimeout(_chatFilterDebounce);
    _chatFilterDebounce = null;
  }
  _chatFilterQuery = "";
  var inp = document.getElementById("chat-filter-input");
  if (inp) inp.value = "";
  _chatFilterApplyNow("");
}
window.chatFilterApply = chatFilterApply;
window.chatFilterReset = chatFilterReset;

/* Voice-recording deferred message queue.
 * When window.isVoiceRecording is true, appendMessage defers the DOM update
 * here instead of immediately mutating the feed. The voice-input module calls
 * window._flushVoiceQueue() when recording stops, which drains the queue. */
var _voiceDeferQueue = [];
window._flushVoiceQueue = function () {
  var queued = _voiceDeferQueue.splice(0);
  queued.forEach(function (msg) {
    appendMessage(msg);
  });
};

function isKnownAgent(name) {
  return cachedAgentNames.indexOf(name) !== -1;
}

/* Cache of GitHub issue titles.
 *   issueTitleCache[number]            → title for the default repo
 *                                        (ywatanabe1989/todo, legacy `#N`)
 *   issueTitleCache["owner/repo#N"]    → title for cross-repo references
 * Negative lookups are stored as the literal string "" so we stop retrying
 * missing issues on every render pass. */
var issueTitleCache = {};
var issueTitleInflight = {};

function _hydrateIssueLink(a, title) {
  if (!title || a.dataset.hinted) return;
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var label = a.getAttribute("data-issue-label") || a.textContent;
  a.title = label + " " + title;
  a.innerHTML =
    escapeHtml(label) +
    ' <span class="issue-link-title">(' +
    escapeHtml(title) +
    ")</span>";
  a.dataset.hinted = "1";
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
}

function _fetchCrossRepoTitle(repo, num, cb) {
  var key = repo + "#" + num;
  if (issueTitleCache[key] !== undefined) {
    cb(issueTitleCache[key] || null);
    return;
  }
  if (issueTitleInflight[key]) return;
  issueTitleInflight[key] = true;
  /* Build the path with query params first, then let apiUrl() add
   * '&token=' (it detects the existing '?' and chooses '&'). The previous
   * version concatenated '?repo=' AFTER apiUrl had already appended
   * '?token=', producing a malformed '?token=...?repo=...' URL → 400. */
  var url = apiUrl(
    "/api/github/issue-title?repo=" +
      encodeURIComponent(repo) +
      "&number=" +
      encodeURIComponent(num),
  );
  fetch(url, { credentials: "same-origin" })
    .then(function (r) {
      return r.ok ? r.json() : null;
    })
    .then(function (data) {
      delete issueTitleInflight[key];
      var title = (data && data.title) || "";
      issueTitleCache[key] = title;
      if (title) cb(title);
    })
    .catch(function () {
      delete issueTitleInflight[key];
    });
}

function applyIssueTitleHints(scope) {
  var root = scope || document;
  root.querySelectorAll(".issue-link").forEach(function (a) {
    if (a.dataset.hinted) return;
    var repo = a.getAttribute("data-issue-repo");
    var num = a.getAttribute("data-issue-num");
    if (!num) {
      var m = a.textContent.match(/#(\d+)/);
      if (!m) return;
      num = m[1];
      a.setAttribute("data-issue-num", num);
    }
    if (repo) {
      /* Cross-repo: hit the per-issue endpoint lazily. */
      var key = repo + "#" + num;
      var cached = issueTitleCache[key];
      if (cached) {
        _hydrateIssueLink(a, cached);
      } else if (cached === undefined) {
        _fetchCrossRepoTitle(repo, num, function (title) {
          _hydrateIssueLink(a, title);
        });
      }
    } else {
      /* Legacy bare `#N` → ywatanabe1989/todo, served from the list cache. */
      var title = issueTitleCache[num];
      if (title) _hydrateIssueLink(a, title);
    }
  });
}

async function refreshIssueTitleCache() {
  try {
    var res = await fetch(apiUrl("/api/github/issues"), {
      credentials: "same-origin",
    });
    if (!res.ok) return;
    var issues = await res.json();
    if (Array.isArray(issues)) {
      issues.forEach(function (i) {
        if (i && i.number && i.title)
          issueTitleCache[String(i.number)] = i.title;
      });
      applyIssueTitleHints();
    }
  } catch (e) {
    /* ignore */
  }
}
/* Refresh on load and every 2 minutes */
refreshIssueTitleCache();
setInterval(refreshIssueTitleCache, 120000);
