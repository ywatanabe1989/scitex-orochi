// @ts-nocheck
import { apiUrl, escapeHtml, userName } from "../app/utils";
import { appendMessage } from "./chat-render";

/* Chat module -- message display, history, filtering */
/* globals: escapeHtml, getAgentColor, timeAgo, (globalThis as any).cachedAgentNames, userName,
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
export var _mentionRegexCache = null;
export function _mentionRegex() {
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
export function _pulseSidebarRow(channel, variant) {
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
export var _chatFilterQuery = "";
export var _chatFilterDebounce = null;
export function _chatFilterApplyNow(q) {
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
export function chatFilterApply(q) {
  if (_chatFilterDebounce) clearTimeout(_chatFilterDebounce);
  _chatFilterDebounce = setTimeout(function () {
    _chatFilterDebounce = null;
    _chatFilterApplyNow(q);
  }, 100);
}
export function chatFilterReset() {
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
export var _voiceDeferQueue = [];
window._flushVoiceQueue = function () {
  var queued = _voiceDeferQueue.splice(0);
  queued.forEach(function (msg) {
    appendMessage(msg);
  });
};

export function isKnownAgent(name) {
  return (globalThis as any).cachedAgentNames.indexOf(name) !== -1;
}

/* Cache of GitHub issue titles.
 *   issueTitleCache["owner/repo#N"]    → title for cross-repo references
 * (Bare `#N` legacy entries are no longer produced; see #275.)
 * Negative lookups are stored as the literal string "" so we stop retrying
 * missing issues on every render pass.
 *
 * Persistence (#275 Part 2): the cache is mirrored to
 * localStorage['orochi.issueTitleCache.v1'] as {key: {title, ts}} with a
 * 24h TTL per entry. On module load we hydrate the in-memory cache from
 * localStorage, dropping expired entries. On every successful title
 * fetch we write the cache back. Storage failures are swallowed (quota,
 * privacy-mode, corrupted JSON — never break the chat UI). */
export var issueTitleCache: Record<string, string> = {};
export var issueTitleInflight: Record<string, boolean> = {};

var ISSUE_TITLE_LS_KEY = "orochi.issueTitleCache.v1";
var ISSUE_TITLE_TTL_MS = 24 * 60 * 60 * 1000; /* 24 hours */

/* Pull persisted entries into the in-memory cache. Called once at module
 * load. Expired or malformed entries are silently discarded. */
(function _hydrateIssueTitleCacheFromLS() {
  try {
    var raw = localStorage.getItem(ISSUE_TITLE_LS_KEY);
    if (!raw) return;
    var obj = JSON.parse(raw);
    if (!obj || typeof obj !== "object") return;
    var now = Date.now();
    Object.keys(obj).forEach(function (k) {
      var v = obj[k];
      if (!v || typeof v !== "object") return;
      if (typeof v.ts !== "number") return;
      if (now - v.ts > ISSUE_TITLE_TTL_MS) return;
      if (typeof v.title === "string") issueTitleCache[k] = v.title;
    });
  } catch (_e) {
    /* ignore: corrupt JSON, storage denied, etc. */
  }
})();

/* Rewrite the persisted cache from the current in-memory state.
 * Debounced via rAF to coalesce bursts of writes from prefetch loops. */
var _issueTitleLSWritePending = false;
function _persistIssueTitleCache() {
  if (_issueTitleLSWritePending) return;
  _issueTitleLSWritePending = true;
  var flush = function () {
    _issueTitleLSWritePending = false;
    try {
      var now = Date.now();
      var out: Record<string, { title: string; ts: number }> = {};
      Object.keys(issueTitleCache).forEach(function (k) {
        /* Persist only positive lookups — negative ("") entries are
         * cheap to re-derive and would pollute storage. */
        var t = issueTitleCache[k];
        if (t) out[k] = { title: t, ts: now };
      });
      localStorage.setItem(ISSUE_TITLE_LS_KEY, JSON.stringify(out));
    } catch (_e) {
      /* ignore: quota, privacy, etc. */
    }
  };
  if (typeof requestAnimationFrame === "function") {
    requestAnimationFrame(flush);
  } else {
    setTimeout(flush, 0);
  }
}

export function _hydrateIssueLink(a, title) {
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

export function _fetchCrossRepoTitle(repo, num, cb) {
  var key = repo + "#" + num;
  if (issueTitleCache[key] !== undefined) {
    if (cb) cb(issueTitleCache[key] || null);
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
      if (title) {
        _persistIssueTitleCache();
        if (cb) cb(title);
      }
    })
    .catch(function () {
      delete issueTitleInflight[key];
    });
}

/* Background prefetch for `owner/repo#N` references in freshly-rendered
 * message HTML (#275 Part 2). Batches cache misses so a burst of new
 * messages coalesces into a single debounced flush (50ms) rather than
 * N independent network calls. The inflight guard inside
 * _fetchCrossRepoTitle prevents duplicate network calls for the same
 * key, so re-enqueueing is safe. */
var _prefetchQueue: Array<{ repo: string; num: string }> = [];
var _prefetchCallbacks: Array<(title: string, key: string) => void> = [];
var _prefetchTimer: any = null;

function _schedulePrefetchFlush(cb?: (title: string, key: string) => void) {
  if (cb) _prefetchCallbacks.push(cb);
  if (_prefetchTimer) return;
  _prefetchTimer = setTimeout(function () {
    _prefetchTimer = null;
    var batch = _prefetchQueue.splice(0);
    var callbacks = _prefetchCallbacks.splice(0);
    /* Dedup within the batch */
    var seen: Record<string, boolean> = {};
    batch.forEach(function (p) {
      var k = p.repo + "#" + p.num;
      if (seen[k]) return;
      seen[k] = true;
      _fetchCrossRepoTitle(p.repo, p.num, function (title) {
        callbacks.forEach(function (c) {
          try {
            c(title, k);
          } catch (_e) {
            /* swallow */
          }
        });
      });
    });
  }, 50);
}

export function prefetchIssueTitlesFromHtml(htmlOrNode: string | Element) {
  var html =
    typeof htmlOrNode === "string"
      ? htmlOrNode
      : (htmlOrNode as Element).innerHTML || "";
  if (!html) return;
  /* The rendered <a class="issue-link"> carries data-issue-repo +
   * data-issue-num — easier to parse than re-running the markdown regex.
   * Match both attribute orderings just in case. */
  var re =
    /data-issue-repo="([^"]+)"[^>]*data-issue-num="([^"]+)"|data-issue-num="([^"]+)"[^>]*data-issue-repo="([^"]+)"/g;
  var m: RegExpExecArray | null;
  var found = 0;
  while ((m = re.exec(html)) !== null) {
    var repo = m[1] || m[4];
    var num = m[2] || m[3];
    if (!repo || !num) continue;
    var key = repo + "#" + num;
    if (issueTitleCache[key] !== undefined) continue;
    if (issueTitleInflight[key]) continue;
    _prefetchQueue.push({ repo: repo, num: num });
    found++;
  }
  if (found > 0) _schedulePrefetchFlush();
}
(globalThis as any).prefetchIssueTitlesFromHtml = prefetchIssueTitlesFromHtml;

export function applyIssueTitleHints(scope) {
  var root = scope || document;
  var uncached: Array<{ a: Element; repo: string; num: string }> = [];
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
    /* Only cross-repo `owner/repo#N` links carry a hint now (#275).
     * Links without data-issue-repo are legacy/external and stay unhinted. */
    if (!repo) return;
    var key = repo + "#" + num;
    var cached = issueTitleCache[key];
    if (cached) {
      _hydrateIssueLink(a, cached);
    } else if (cached === undefined) {
      uncached.push({ a: a, repo: repo, num: num });
    }
  });
  /* Dispatch the misses through the debounced prefetch queue so a burst
   * of new messages coalesces into a single batch of fetches (#275). */
  if (uncached.length > 0) {
    uncached.forEach(function (u) {
      _prefetchQueue.push({ repo: u.repo, num: u.num });
    });
    _schedulePrefetchFlush(function (title, key) {
      /* Hydrate all matching links now that the fetch resolved. */
      uncached.forEach(function (u) {
        if (u.repo + "#" + u.num === key && title) {
          _hydrateIssueLink(u.a, title);
        }
      });
    });
  }
}

/* Kept as a named export for back-compat with modules that still import
 * it. The legacy body (pre-seeding the cache with a GET /api/github/issues
 * dump of ywatanabe1989/todo) was removed along with the bare `#N`
 * auto-linker (#275) — cross-repo refs populate the cache on demand and
 * are now persisted via localStorage instead. */
export async function refreshIssueTitleCache() {
  /* no-op retained for import compatibility */
}

// Expose cross-file mutable state via globalThis:
(globalThis as any)._initialLoadComplete = (typeof _initialLoadComplete !== 'undefined' ? _initialLoadComplete : undefined);
(globalThis as any)._isLoadingHistory = (typeof _isLoadingHistory !== 'undefined' ? _isLoadingHistory : undefined);
