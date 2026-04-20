
async function fetchStats() {
  try {
    var res = await fetch(apiUrl("/api/stats"));
    var stats = await res.json();
    var chContainer = document.getElementById("channels");
    var newStatsJson = JSON.stringify(stats.channels);
    if (chContainer._lastStatsJson === newStatsJson) return;
    chContainer._lastStatsJson = newStatsJson;
    var msgInput = document.getElementById("msg-input");
    var inputHasFocus = msgInput && document.activeElement === msgInput;
    var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
    var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
    /* Preserve Ctrl+Click multi-select state across re-renders (#274 Part 2) */
    var prevSelected = {};
    chContainer
      .querySelectorAll(".channel-item.selected")
      .forEach(function (el) {
        var ch = el.getAttribute("data-channel");
        if (ch) prevSelected[ch] = true;
      });
    /* todo#325: hide dm:* channels from the public Channels list
     * (they still render in the DM tab via its own path).
     * todo#326: normalize "general" -> "#general" and dedupe by
     * normalized name so legacy rows collapse into a single entry. */
    var seenNames = {};
    var displayChannels = [];
    /* todo#418: hidden channels always render, but dimmed at the bottom of
     * the Channels section. Clicking a dimmed row un-hides it. No separate
     * toggle UI or per-row eye button — just a subtle visual sort-to-bottom
     * so the list stays scannable. */
    stats.channels.forEach(function (c) {
      if (typeof c !== "string") return;
      if (c.indexOf("dm:") === 0) return;
      var norm = c.charAt(0) === "#" ? c : "#" + c;
      if (seenNames[norm]) return;
      seenNames[norm] = true;
      var pref = _channelPrefs[norm] || _channelPrefs[c] || {};
      displayChannels.push({
        raw: c,
        norm: norm,
        hidden: !!pref.is_hidden,
      });
    });
    /* Also include channels that only exist in _channelPrefs with is_hidden
     * (e.g. deleted from server list but kept for un-hiding). */
    Object.keys(_channelPrefs).forEach(function (ch) {
      if (typeof ch !== "string") return;
      if (ch.indexOf("dm:") === 0) return;
      var pref = _channelPrefs[ch];
      if (!pref || !pref.is_hidden) return;
      var norm = ch.charAt(0) === "#" ? ch : "#" + ch;
      if (seenNames[norm]) return;
      seenNames[norm] = true;
      displayChannels.push({ raw: ch, norm: norm, hidden: true });
    });
    /* Sort: starred first, then visible, then hidden rows at bottom. */
    displayChannels.sort(function (a, b) {
      if (!!a.hidden !== !!b.hidden) return a.hidden ? 1 : -1;
      var pa = _channelPrefs[a.norm] || _channelPrefs[a.raw] || {};
      var pb = _channelPrefs[b.norm] || _channelPrefs[b.raw] || {};
      var aStarred = pa.is_starred ? 0 : 1;
      var bStarred = pb.is_starred ? 0 : 1;
      if (aStarred !== bStarred) return aStarred - bStarred;
      var oa = pa.sort_order != null ? pa.sort_order : 9999;
      var ob = pb.sort_order != null ? pb.sort_order : 9999;
      return oa !== ob ? oa - ob : a.norm.localeCompare(b.norm);
    });
    /* Track first-hidden index so we can drop a subtle divider before
     * the hidden block (todo#418). */
    var firstHiddenIdx = -1;
    for (var _i = 0; _i < displayChannels.length; _i++) {
      if (displayChannels[_i].hidden) {
        firstHiddenIdx = _i;
        break;
      }
    }
    /* todo#71: tree-structured channel hierarchy via "/" path segments.
     * Channels named like "proj/ripple-wm" are grouped under a collapsible
     * "proj" folder header. Starred (pinned) channels remain flat at the
     * top — pinning means "always visible". Hidden channels also stay flat
     * at the bottom (already visually separated by the divider).
     *
     * No backend change. `mkdir` is a no-op (folder appears when first
     * child is added). `mv` is just a channel rename (deferred until a
     * rename API exists). Collapse state persists in localStorage so
     * refreshes keep the user's folders closed/open as they left them. */
    var _treeCollapsed = {};
    try {
      var _raw = localStorage.getItem("orochi.channelTreeCollapsed");
      if (_raw) _treeCollapsed = JSON.parse(_raw) || {};
    } catch (_) {
      _treeCollapsed = {};
    }
    /* Parse "#proj/ripple-wm" -> { folder: "proj", leaf: "#ripple-wm" }.
     * Returns null if the channel has no folder (top-level). Only splits
     * on the FIRST "/" to keep it simple — deeply nested trees can be
     * added later if needed. */
    function _splitChannelPath(norm) {
      if (typeof norm !== "string" || norm.length === 0) return null;
      /* Strip leading "#" then look for "/" */
      var bare = norm.charAt(0) === "#" ? norm.slice(1) : norm;
      var slash = bare.indexOf("/");
      if (slash <= 0 || slash === bare.length - 1) return null;
      return {
        folder: bare.slice(0, slash),
        leaf: "#" + bare.slice(slash + 1),
      };
    }
    /* Walk displayChannels in sorted order and emit an interleaved list of
     * folder-header rows + channel rows. Only non-starred, non-hidden
     * channels are tree-ified; starred stays pinned flat at the top, and
     * hidden stays dimmed flat at the bottom. */
    var _currentFolder = null;
    var _renderRows = [];
    for (var _ri = 0; _ri < displayChannels.length; _ri++) {
      var _e = displayChannels[_ri];
      var _epref = _channelPrefs[_e.norm] || _channelPrefs[_e.raw] || {};
      var _isStarred = !!_epref.is_starred;
      var _isHidden = !!_e.hidden;
      var _split =
        !_isStarred && !_isHidden ? _splitChannelPath(_e.norm) : null;
      if (_split) {
        if (_currentFolder !== _split.folder) {
          _currentFolder = _split.folder;
          _renderRows.push({
            type: "folder",
            prefix: _split.folder,
            collapsed: !!_treeCollapsed[_split.folder],
          });
        }
        if (_treeCollapsed[_split.folder]) {
          /* Child hidden by collapsed folder — skip rendering the row. */
          continue;
        }
        _renderRows.push({
          type: "channel",
          entry: _e,
          origIdx: _ri,
          inFolder: _split.folder,
          leafLabel: _split.leaf,
        });
      } else {
        _currentFolder = null;
        _renderRows.push({
          type: "channel",
          entry: _e,
          origIdx: _ri,
          inFolder: null,
          leafLabel: _e.norm,
        });
      }
    }
    chContainer.innerHTML = _renderRows
      .map(function (row) {
        if (row.type === "folder") {
          var chev = row.collapsed ? "\u25B8" : "\u25BE"; /* ▸ ▾ */
          var ficon = row.collapsed
            ? "\uD83D\uDCC1"
            : "\uD83D\uDCC2"; /* 📁 📂 */
          return (
            '<div class="channel-folder' +
            (row.collapsed ? " collapsed" : "") +
            '" data-folder="' +
            escapeHtml(row.prefix) +
            '" title="Click to ' +
            (row.collapsed ? "expand" : "collapse") +
            ' folder">' +
            '<span class="ch-folder-chev">' +
            chev +
            "</span>" +
            '<span class="ch-folder-icon">' +
            ficon +
            "</span>" +
            '<span class="ch-folder-name">' +
            escapeHtml(row.prefix) +
            "/</span>" +
            "</div>"
          );
        }
        var entry = row.entry;
        var i = row.origIdx;
        var c = entry.raw;
        var norm = entry.norm;
        var active = currentChannel === c ? " active" : "";
        var pref = _channelPrefs[norm] || _channelPrefs[c] || {};
        var muted = pref.is_muted ? " ch-muted" : "";
        /* Star = float-to-top (pinned). ★ filled for starred, ☆ outline
         * for unstarred. Replaces the earlier 📌 pin emoji so both canvas
         * pool chips and this list use a single standardized icon. */
        /* Entity-consistency order from TODO.md:
         *   channel: [icon] [star] [hide] [notification] [#name]
         * Three control glyphs kept as separate slots so they can be
         * interleaved with the identity icon below. */
        var pinGlyphHtml =
          '<span class="ch-pin ' +
          (pref.is_starred ? "ch-pin-on" : "ch-pin-off") +
          '" data-ch="' +
          escapeHtml(norm) +
          '" title="' +
          (pref.is_starred ? "Unstar" : "Star (float to top)") +
          '">' +
          (pref.is_starred ? "\u2605" : "\u2606") +
          "</span>";
        var hideGlyphHtml =
          '<span class="ch-eye ' +
          (pref.is_hidden ? "ch-eye-off" : "ch-eye-on") +
          '" data-ch="' +
          escapeHtml(norm) +
          '" title="' +
          (pref.is_hidden
            ? "Show channel (un-hide)"
            : "Hide channel (dim in list)") +
          '">' +
          (pref.is_hidden ? "\uD83D\uDEAB" : "\uD83D\uDC41") +
          "</span>";
        var muteGlyphHtml =
          '<span class="ch-mute ' +
          (pref.is_muted ? "ch-mute-on" : "ch-mute-off") +
          '" data-ch="' +
          escapeHtml(norm) +
          '" title="' +
          (pref.is_muted ? "Unmute notifications" : "Mute notifications") +
          '">' +
          (pref.is_muted ? "\uD83D\uDD15" : "\uD83D\uDD14") +
          "</span>";
        var unread = channelUnread[c] || channelUnread[norm] || 0;
        var badgeHtml =
          '<span class="ch-badge-slot">' +
          (unread > 0
            ? '<span class="unread-badge">' +
              (unread > 99 ? "99+" : unread) +
              "</span>"
            : "") +
          "</span>";
        var starred = pref.is_starred ? " ch-starred" : "";
        var hiddenCls = entry.hidden ? " ch-hidden" : "";
        var inFolderCls = row.inFolder ? " ch-in-folder" : "";
        var divider =
          i === firstHiddenIdx
            ? '<div class="ch-hidden-divider" aria-hidden="true"></div>'
            : "";
        var rowTitle = entry.hidden
          ? ' title="Hidden \u2014 click to un-hide"'
          : row.inFolder
            ? ' title="' + escapeHtml(entry.norm) + '"'
            : "";
        /* Label: full "#proj/ripple-wm" at top level; short "#ripple-wm"
         * when rendered as a child of the proj/ folder header (todo#71). */
        var nameLabel = row.inFolder ? row.leafLabel : entry.norm;
        return (
          divider +
          '<div class="channel-item' +
          active +
          muted +
          starred +
          hiddenCls +
          inFolderCls +
          '" data-channel="' +
          escapeHtml(c) +
          '"' +
          (entry.hidden ? ' data-hidden="1"' : "") +
          (row.inFolder
            ? ' data-folder="' + escapeHtml(row.inFolder) + '"'
            : "") +
          rowTitle +
          ' draggable="true">' +
          '<span class="ch-drag-handle" title="Drag to reorder">&#8942;</span>' +
          /* [icon] [star] [hide] [notification] [#name] — entity
           * consistency spec. channelIdentity() is the single source
           * of truth for the icon; the three control glyphs stay in
           * the fixed order below. */
          (typeof channelIdentity === "function"
            ? '<span class="ch-identity-icon">' +
              channelIdentity(norm).iconHtml(14) +
              "</span>"
            : "") +
          pinGlyphHtml +
          hideGlyphHtml +
          muteGlyphHtml +
          '<span class="ch-name">' +
          escapeHtml(nameLabel) +
          "</span>" +
          badgeHtml +
          "</div>"
        );
      })
      .join("");
    /* todo#71: wire folder-header click -> toggle collapse + persist.
     * Handler is attached BEFORE the .channel-item forEach so the folder
     * rows live in the same DOM snapshot. Clicking a folder re-runs
     * fetchStats() via the localStorage round-trip so the next render
     * reflects the new collapse state immediately. */
    chContainer.querySelectorAll(".channel-folder").forEach(function (fEl) {
      fEl.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var prefix = fEl.getAttribute("data-folder") || "";
        if (!prefix) return;
        var store = {};
        try {
          var raw = localStorage.getItem("orochi.channelTreeCollapsed");
          if (raw) store = JSON.parse(raw) || {};
        } catch (_) {
          store = {};
        }
        if (store[prefix]) {
          delete store[prefix];
        } else {
          store[prefix] = true;
        }
        try {
          localStorage.setItem(
            "orochi.channelTreeCollapsed",
            JSON.stringify(store),
          );
        } catch (_) {}
        /* Bust the throttle so the next fetchStats actually re-renders. */
        chContainer._lastStatsJson = null;
        fetchStats();
      });
    });
    chContainer.querySelectorAll(".channel-item").forEach(function (el) {
      /* Restore selected state from before re-render */
      var elCh = el.getAttribute("data-channel");
      if (elCh && prevSelected[elCh]) el.classList.add("selected");
      /* Pin icon click — toggle is_starred (pinned-to-top) */
      var pinEl = el.querySelector(".ch-pin");
      if (pinEl) {
        pinEl.addEventListener("click", function (ev) {
          ev.stopPropagation();
          var norm = pinEl.getAttribute("data-ch");
          var curPref = _channelPrefs[norm] || {};
          _setChannelPref(norm, { is_starred: !curPref.is_starred });
        });
      }
      /* Eye icon click — toggle is_muted (watching vs muted) */
      var watchEl = el.querySelector(".ch-watch");
      if (watchEl) {
        watchEl.addEventListener("click", function (ev) {
          ev.stopPropagation();
          var norm = watchEl.getAttribute("data-ch");
          var curPref = _channelPrefs[norm] || {};
          _setChannelPref(norm, { is_muted: !curPref.is_muted });
        });
      }
      /* Bell/mute placeholder click — toggle is_muted. Placeholder is
       * always rendered (reserved slot) so channel-name columns line up
       * whether the row is muted or not. */
      var muteEl = el.querySelector(".ch-mute");
      if (muteEl) {
        muteEl.addEventListener("click", function (ev) {
          ev.stopPropagation();
          ev.preventDefault();
          var norm = muteEl.getAttribute("data-ch");
          var curPref = _channelPrefs[norm] || {};
          _setChannelPref(norm, { is_muted: !curPref.is_muted });
        });
      }
      /* Hide/unhide icon click — toggle is_hidden (todo#418). */
      var eyeEl = el.querySelector(".ch-eye");
      if (eyeEl) {
        eyeEl.addEventListener("click", function (ev) {
          ev.stopPropagation();
          ev.preventDefault();
          var norm = eyeEl.getAttribute("data-ch");
          var curPref = _channelPrefs[norm] || {};
          _setChannelPref(norm, { is_hidden: !curPref.is_hidden });
        });
      }
      /* Context menu */
      _addChannelContextMenu(el);
      /* todo#49: accept agent-card drops to toggle subscription. */
      el.addEventListener("dragover", function (ev) {
        var drag = window.__orochiDragAgent;
        if (!drag || !drag.name) return;
        ev.preventDefault();
        ev.dataTransfer.dropEffect = "link";
        var ch = el.getAttribute("data-channel") || "";
        var subscribed = _agentHasChannel(drag.channels, ch);
        if (subscribed) {
          el.classList.add("drop-target-agent-remove");
          el.classList.remove("drop-target-agent-add");
          _setChannelDropHint(el, "drop to unsubscribe");
        } else {
          el.classList.add("drop-target-agent-add");
          el.classList.remove("drop-target-agent-remove");
          _setChannelDropHint(el, "drop to subscribe");
        }
      });
      el.addEventListener("dragleave", function () {
        el.classList.remove("drop-target-agent-add");
        el.classList.remove("drop-target-agent-remove");
        var hint = el.querySelector(".ch-hint");
        if (hint) hint.remove();
      });
      el.addEventListener("drop", function (ev) {
        var agentName =
          (ev.dataTransfer &&
            ev.dataTransfer.getData("application/x-orochi-agent")) ||
          (window.__orochiDragAgent && window.__orochiDragAgent.name) ||
          "";
        if (!agentName) return;
        ev.preventDefault();
        ev.stopPropagation();
        var ch = el.getAttribute("data-channel") || "";
        var chs =
          (ev.dataTransfer &&
            ev.dataTransfer.getData("application/x-orochi-agent-channels")) ||
          (window.__orochiDragAgent && window.__orochiDragAgent.channels) ||
          "";
        var subscribed = _agentHasChannel(chs, ch);
        el.classList.remove("drop-target-agent-add");
        el.classList.remove("drop-target-agent-remove");
        var hint = el.querySelector(".ch-hint");
        if (hint) hint.remove();
        _toggleAgentChannelSubscription(agentName, ch, !subscribed);
      });
      el.addEventListener("click", function (ev) {
        if (
          ev.target.classList.contains("ch-pin") ||
          ev.target.classList.contains("ch-watch") ||
          ev.target.classList.contains("ch-mute") ||
          ev.target.classList.contains("ch-eye") ||
          ev.target.classList.contains("ch-drag-handle")
        )
          return;
        var ch = el.getAttribute("data-channel");
        /* Hidden row click: un-hide (same call path as ctx-menu "Show channel"). */
        if (el.getAttribute("data-hidden") === "1") {
          ev.stopPropagation();
          _setChannelPref(ch, { is_hidden: false });
          return;
        }
        var multi = ev.ctrlKey || ev.metaKey;
        /* todo#274 Part 2: Ctrl/Cmd+Click toggles multi-select without
         * disturbing siblings; plain click keeps legacy single-select. */
        if (multi) {
          el.classList.toggle("selected");
          /* When multi-select is active, the DOM may only have messages from
           * currentChannel. Switch to all-channel history so messages from
           * every selected channel are present, then let applyFeedFilter
           * show the merged subset. (#366) */
          var _selCount = chContainer.querySelectorAll(
            ".channel-item.selected[data-channel]",
          ).length;
          if (_selCount >= 2) {
            /* Load all messages; applyFeedFilter handles visible subset */
            setCurrentChannel(null);
            var _applyAfter = function () {
              if (typeof applyFeedFilter === "function") applyFeedFilter();
            };
            loadHistory().then
              ? loadHistory().then(_applyAfter)
              : (loadHistory(), _applyAfter());
          } else if (_selCount === 1) {
            var _onlyCh = chContainer.querySelector(
              ".channel-item.selected[data-channel]",
            );
            if (_onlyCh) {
              setCurrentChannel(_onlyCh.getAttribute("data-channel"));
              loadChannelHistory(_onlyCh.getAttribute("data-channel"));
            }
          } else {
            /* All deselected */
            if (typeof applyFeedFilter === "function") applyFeedFilter();
          }
          return;
        }
        if (currentChannel === ch) {
          setCurrentChannel(null);
          loadHistory();
        } else {
          setCurrentChannel(ch);
          loadChannelHistory(ch);
        }
        /* Auto-switch to Chat tab when channel is clicked (#335) */
        if (typeof _activateTab === "function" && activeTab !== "chat") {
          _activateTab("chat");
        }
        /* Clear unread for this channel (#322) */
        channelUnread[ch] = 0;
        updateChannelUnreadBadges();
        /* todo#274 Part 1: pure visual highlight, toggle on second click. */
        var items = chContainer.querySelectorAll(".channel-item");
        var wasSelected = el.classList.contains("selected");
        items.forEach(function (it) {
          it.classList.remove("selected");
        });
        if (!wasSelected && currentChannel === ch) {
          el.classList.add("selected");
        }
        if (typeof applyFeedFilter === "function") applyFeedFilter();
        fetchStats();
      });
    });
    var chCountEl = document.getElementById("sidebar-count-channels");
    if (chCountEl) {
      /* Count visible (non-hidden) rows for the heading — the dimmed
       * hidden rows at the bottom are intentionally not in this count. */
      var visibleCount = displayChannels.filter(function (e) {
        return !e.hidden;
      }).length;
      chCountEl.textContent = "(" + visibleCount + ")";
    }
    /* Add drag-and-drop to channels section */
    _addDragAndDrop(chContainer, "channels");
    if (typeof updateChannelUnreadBadges === "function")
      updateChannelUnreadBadges();
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try {
        msgInput.setSelectionRange(savedStart, savedEnd);
      } catch (_) {}
    }
  } catch (e) {
    /* fetch error */
  }
}
/* Init is deferred to init.js (loaded after all modules) */
