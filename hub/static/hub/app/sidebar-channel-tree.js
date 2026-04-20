/* Channel-tree render + per-row handler helpers used by fetchStats()
 * in sidebar-stats.js. Split out as a sibling classic-script file so
 * sidebar-stats.js stays under the per-file line budget. Pure cut &
 * paste — zero behavioral change. Must be loaded BEFORE sidebar-stats.js
 * in dashboard.html so the helpers resolve at call time. */

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
function _buildRenderRows(displayChannels, channelPrefs, treeCollapsed) {
  var currentFolder = null;
  var renderRows = [];
  for (var ri = 0; ri < displayChannels.length; ri++) {
    var e = displayChannels[ri];
    var epref = channelPrefs[e.norm] || channelPrefs[e.raw] || {};
    var isStarred = !!epref.is_starred;
    var isHidden = !!e.hidden;
    var split = !isStarred && !isHidden ? _splitChannelPath(e.norm) : null;
    if (split) {
      if (currentFolder !== split.folder) {
        currentFolder = split.folder;
        renderRows.push({
          type: "folder",
          prefix: split.folder,
          collapsed: !!treeCollapsed[split.folder],
        });
      }
      if (treeCollapsed[split.folder]) {
        /* Child hidden by collapsed folder — skip rendering the row. */
        continue;
      }
      renderRows.push({
        type: "channel",
        entry: e,
        origIdx: ri,
        inFolder: split.folder,
        leafLabel: split.leaf,
      });
    } else {
      currentFolder = null;
      renderRows.push({
        type: "channel",
        entry: e,
        origIdx: ri,
        inFolder: null,
        leafLabel: e.norm,
      });
    }
  }
  return renderRows;
}

/* Render a folder-header row (collapsible tree group). */
function _renderFolderRowHtml(row) {
  var chev = row.collapsed ? "\u25B8" : "\u25BE"; /* ▸ ▾ */
  var ficon = row.collapsed ? "\uD83D\uDCC1" : "\uD83D\uDCC2"; /* 📁 📂 */
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

/* Render a single channel row (or a hidden-divider + row).
 * ctx carries per-render state: firstHiddenIdx + current channel. */
function _renderChannelRowHtml(row, ctx) {
  var entry = row.entry;
  var i = row.origIdx;
  var c = entry.raw;
  var norm = entry.norm;
  var active = ctx.currentChannel === c ? " active" : "";
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
    (pref.is_hidden ? "Show channel (un-hide)" : "Hide channel (dim in list)") +
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
    i === ctx.firstHiddenIdx
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
    (row.inFolder ? ' data-folder="' + escapeHtml(row.inFolder) + '"' : "") +
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
}

/* Wire click/drag/context-menu handlers on every .channel-item currently in
 * chContainer. Pulled out of fetchStats so the main entry point stays under
 * the file-size budget without changing any observable behavior. */
function _wireChannelItemHandlers(chContainer, prevSelected) {
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
}
