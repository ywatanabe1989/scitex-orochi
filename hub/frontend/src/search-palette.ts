// @ts-nocheck
/* Search Palette — Ctrl+K / Cmd+K global command palette (todo#365)
 *
 * Depends on: app.js (apiUrl, token), mention.js (fuzzyMatch >= 0 → _fm)
 * Reuses: _fm() from filter.js (loaded before this file), openThreadForMessage()
 * from threads.js, jumpToMsg() from chat.js.
 *
 * API: GET /api/messages/?limit=200 — fetch once per session, then filter
 * client-side.  A new fetch is issued whenever the cache is stale (>60 s)
 * or when the user presses Ctrl+K again after that window.
 */

(function () {
  "use strict";

  /* ── state ────────────────────────────────────────────────────────────── */
  var _overlay = null;
  var _input   = null;
  var _results = null;
  var _status  = null;
  var _cache   = [];           /* [{id, channel, sender, content, ts}] */
  var _cacheTs = 0;            /* epoch ms of last successful fetch     */
  var _CACHE_TTL = 60 * 1000; /* 60 s                                  */
  var _debounceTimer = null;
  var _selectedIdx = -1;
  var _loading = false;

  /* ── fuzzy helper (reuse filter.js _fm or fall back) ─────────────────── */
  function fm(query, text) {
    if (typeof _fm === "function") return _fm(query, text);
    if (typeof fuzzyMatch === "function") return fuzzyMatch(query, text) >= 0;
    return text.toLowerCase().indexOf(query.toLowerCase()) >= 0;
  }

  /* ── DOM injection ───────────────────────────────────────────────────── */
  function buildDOM() {
    if (_overlay) return;

    _overlay = document.createElement("div");
    _overlay.id = "search-palette-overlay";
    _overlay.setAttribute("role", "dialog");
    _overlay.setAttribute("aria-modal", "true");
    _overlay.setAttribute("aria-label", "Global message search");

    _overlay.innerHTML =
      '<div id="search-palette-modal">' +
        '<div id="search-palette-input-wrap">' +
          '<span id="search-palette-icon" aria-hidden="true">&#128269;</span>' +
          '<input id="search-palette-input" type="text" autocomplete="off"' +
          ' autocorrect="off" autocapitalize="off" spellcheck="false"' +
          ' placeholder="Search messages across all channels\u2026" />' +
          '<span id="search-palette-status"></span>' +
        '</div>' +
        '<div id="search-palette-results" role="listbox"></div>' +
        '<div id="search-palette-footer">' +
          '<span class="sp-hint"><kbd>\u2191</kbd><kbd>\u2193</kbd> navigate</span>' +
          '<span class="sp-hint"><kbd>Enter</kbd> open thread</span>' +
          '<span class="sp-hint"><kbd>Esc</kbd> close</span>' +
        '</div>' +
      '</div>';

    document.body.appendChild(_overlay);

    _input   = document.getElementById("search-palette-input");
    _results = document.getElementById("search-palette-results");
    _status  = document.getElementById("search-palette-status");

    /* Click outside modal → close */
    _overlay.addEventListener("mousedown", function (e) {
      if (e.target === _overlay) closePalette();
    });

    _input.addEventListener("input", function () {
      clearTimeout(_debounceTimer);
      _debounceTimer = setTimeout(runSearch, 150);
    });

    _input.addEventListener("keydown", handleInputKey);
  }

  /* ── open / close ────────────────────────────────────────────────────── */
  function openPalette() {
    buildDOM();
    _overlay.classList.add("sp-open");
    _input.value = "";
    _results.innerHTML = "";
    _status.textContent = "";
    _selectedIdx = -1;
    _input.focus();
    fetchMessages();   /* refresh cache if stale */
  }

  function closePalette() {
    if (!_overlay) return;
    _overlay.classList.remove("sp-open");
    _selectedIdx = -1;
  }

  /* ── API fetch ───────────────────────────────────────────────────────── */
  function fetchMessages() {
    var now = Date.now();
    if (_loading || (now - _cacheTs < _CACHE_TTL && _cache.length > 0)) return;
    _loading = true;
    setStatus("Loading\u2026");

    var url;
    if (typeof apiUrl === "function") {
      url = apiUrl("/api/messages/?limit=200");
    } else {
      url = "/api/messages/?limit=200";
    }

    fetch(url, { credentials: "same-origin" })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        _cache = data;
        _cacheTs = Date.now();
        _loading = false;
        setStatus("");
        /* If the user has already typed something, run search now */
        if (_input && _input.value.trim()) runSearch();
      })
      .catch(function (err) {
        _loading = false;
        setStatus("Failed to load");
        console.warn("[search-palette] fetch error:", err);
      });
  }

  function setStatus(msg) {
    if (_status) _status.textContent = msg;
  }

  /* ── search / render ─────────────────────────────────────────────────── */
  function runSearch() {
    var raw = _input ? _input.value.trim() : "";
    if (!raw) {
      _results.innerHTML = "";
      _selectedIdx = -1;
      return;
    }

    /* AND logic: each space-separated word must match */
    var words = raw.split(/\s+/).filter(Boolean).map(function (w) {
      return w.toLowerCase();
    });

    var hits = _cache.filter(function (msg) {
      var haystack =
        (msg.sender || "") + " " +
        (msg.channel || "") + " " +
        (msg.content || "");
      return words.every(function (w) { return fm(w, haystack); });
    });

    /* Newest first (cache is already ordered by -ts from the API) */
    renderResults(hits.slice(0, 50), words);
  }

  function highlight(text, words) {
    /* Escape HTML, then wrap each matched keyword with <mark> */
    var safe = text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    words.forEach(function (w) {
      /* Simple case-insensitive literal highlight — avoid regex flag compat issues */
      var lower = safe.toLowerCase();
      var wl = w.toLowerCase();
      var out = "";
      var pos = 0;
      var idx;
      while ((idx = lower.indexOf(wl, pos)) !== -1) {
        out += safe.slice(pos, idx) +
               '<mark>' + safe.slice(idx, idx + w.length) + '</mark>';
        pos = idx + w.length;
      }
      out += safe.slice(pos);
      safe = out;
    });
    return safe;
  }

  function formatTs(isoStr) {
    try {
      var d = new Date(isoStr);
      var now = new Date();
      var diff = now - d;
      if (diff < 60000) return "just now";
      if (diff < 3600000) return Math.floor(diff / 60000) + "m ago";
      if (diff < 86400000) return Math.floor(diff / 3600000) + "h ago";
      return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    } catch (_) {
      return "";
    }
  }

  function renderResults(hits, words) {
    _selectedIdx = -1;
    if (hits.length === 0) {
      _results.innerHTML = '<div class="sp-empty">No messages found</div>';
      return;
    }

    var html = hits.map(function (msg, i) {
      var snippet = (msg.content || "").replace(/\s+/g, " ").trim();
      if (snippet.length > 200) snippet = snippet.slice(0, 200) + "\u2026";
      return (
        '<div class="sp-result" role="option" data-msg-id="' + escapeAttr(String(msg.id)) +
        '" data-idx="' + i + '">' +
          '<div class="sp-result-meta">' +
            '<span class="sp-result-channel">' + escapeHtml(msg.channel || "") + '</span>' +
            '<span class="sp-result-sender">' + escapeHtml(msg.sender || "") + '</span>' +
            '<span class="sp-result-ts">' + formatTs(msg.ts) + '</span>' +
          '</div>' +
          '<div class="sp-result-snippet">' + highlight(snippet, words) + '</div>' +
        '</div>'
      );
    }).join("");

    _results.innerHTML = html;

    /* Bind click on each result */
    _results.querySelectorAll(".sp-result").forEach(function (el) {
      el.addEventListener("mousedown", function (e) {
        e.preventDefault(); /* prevent blur on input */
        activateResult(el);
      });
    });
  }

  /* ── keyboard navigation ─────────────────────────────────────────────── */
  function handleInputKey(e) {
    var items = _results.querySelectorAll(".sp-result");
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelected(Math.min(_selectedIdx + 1, items.length - 1), items);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelected(Math.max(_selectedIdx - 1, 0), items);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (_selectedIdx >= 0 && items[_selectedIdx]) {
        activateResult(items[_selectedIdx]);
      } else if (items.length > 0) {
        activateResult(items[0]);
      }
    } else if (e.key === "Escape") {
      closePalette();
    }
  }

  function setSelected(idx, items) {
    items.forEach(function (el) { el.classList.remove("sp-selected"); });
    _selectedIdx = idx;
    if (idx >= 0 && items[idx]) {
      items[idx].classList.add("sp-selected");
      items[idx].scrollIntoView({ block: "nearest" });
    }
  }

  /* ── activate (open thread) ──────────────────────────────────────────── */
  function activateResult(el) {
    var msgId = el.getAttribute("data-msg-id");
    closePalette();
    if (!msgId) return;
    if (typeof jumpToMsg === "function") {
      jumpToMsg(msgId);
    } else if (typeof openThreadForMessage === "function") {
      openThreadForMessage(msgId);
    }
  }

  /* ── escape helpers ──────────────────────────────────────────────────── */
  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escapeAttr(s) {
    return String(s).replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  /* ── global keydown listener ─────────────────────────────────────────── */
  document.addEventListener("keydown", function (e) {
    /* Ctrl+K on all platforms, Cmd+K on Mac */
    var isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
    var trigger = isMac ? (e.metaKey && e.key === "k") : (e.ctrlKey && e.key === "k");
    if (!trigger) return;

    /* Don't intercept when focus is inside an editable element other than
     * the palette input itself */
    var tag = document.activeElement && document.activeElement.tagName;
    var isEditable =
      (tag === "INPUT" || tag === "TEXTAREA" || document.activeElement.isContentEditable) &&
      document.activeElement.id !== "search-palette-input";
    if (isEditable) return;

    e.preventDefault();
    if (_overlay && _overlay.classList.contains("sp-open")) {
      closePalette();
    } else {
      openPalette();
    }
  });

  /* ── expose for external use (e.g. a toolbar button) ─────────────────── */
  window.openSearchPalette = openPalette;
  window.closeSearchPalette = closePalette;
})();
