// @ts-nocheck
import { _agentHasChannel, _setChannelDropHint, _toggleAgentChannelSubscription } from "./agent-actions";
import { _setChannelPref } from "./channel-prefs";
import { _addChannelContextMenu } from "./context-menus";
import { _channelPrefs } from "./members";
import { fetchStats } from "./sidebar-stats";
import { setCurrentChannel } from "./state";
import { channelUnread, escapeHtml, getAgentColor } from "./utils";
import { updateChannelUnreadBadges } from "./websocket";
import { channelBadgeModel, renderChannelBadgeHtml } from "../channel-badge";
import { loadChannelHistory } from "../chat/chat-history";
import { applyFeedFilter } from "../chat/chat-render";
import { _activateTab, activeTab } from "../tabs";

/* Channel-tree render + per-row handler helpers used by fetchStats()
 * in sidebar-stats.js. Split out as a sibling classic-script file so
 * sidebar-stats.js stays under the per-file line budget. Pure cut &
 * paste — zero behavioral change. Must be loaded BEFORE sidebar-stats.js
 * in dashboard.html so the helpers resolve at call time. */

/* Parse "#proj/ripple-wm" -> { folder: "proj", leaf: "#ripple-wm" }.
 * Returns null if the channel has no folder (top-level). Only splits
 * on the FIRST "/" to keep it simple — deeply nested trees can be
 * added later if needed. */
export function _splitChannelPath(norm) {
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
export function _buildRenderRows(displayChannels, channelPrefs, treeCollapsed) {
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
export function _renderFolderRowHtml(row) {
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
export function _renderChannelRowHtml(row, ctx) {
  var entry = row.entry;
  var i = row.origIdx;
  var c = entry.raw;
  var norm = entry.norm;
  var active = ctx.currentChannel === c ? " active" : "";
  var pref = _channelPrefs[norm] || _channelPrefs[c] || {};
  var muted = pref.is_muted ? " ch-muted" : "";
  /* Inner badge markup (icon/star/eye/mute/name/unread) comes from
   * channel-badge.js — single source of truth shared with the pool
   * chip + canvas SVG. Star/eye/mute clicks are handled by the
   * body-level delegation wired in attachChannelBadgeHandlers(). */
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
  /* Single source of truth for the inner badge markup — icon / star /
   * eye / mute / name / unread. Identical call surface as the pool
   * chip and the SVG node so clicks + geometry stay in lockstep.
   * See channel-badge.js. The outer .channel-item wrapper keeps the
   * sidebar-only classes (active/muted/starred/hidden/in-folder) that
   * CSS and drag/drop already depend on. */
  var badgeInner =
    typeof renderChannelBadgeHtml === "function"
      ? renderChannelBadgeHtml(c, {
          context: "sidebar",
          showEye: true,
          showUnread: true,
          draggable: true,
          label: nameLabel,
          iconSize: 14,
        })
      : "";
  /* todo#305 (ywatanabe msg#15510 / lead msg#15513): restore per-channel
   * colour to the sidebar row. PR #285 dropped row-level colour-coding;
   * the directive has since been reversed. Palette source = the SAME
   * name-hash used by agent cards (getAgentColor → OROCHI_COLORS), so
   * Channels and Agents lists share a coherent colour vocabulary.
   *
   * Apply via the --channel-accent CSS custom property on the row. CSS
   * in style-channels.css tints the leading .ch-identity-icon glyph and
   * draws a 2px left-edge accent stripe from this var. Nothing else on
   * the row is coloured: no row background tint (PR #293's subtle
   * selected-bg rule owns selection signalling) and no opacity change
   * (PR #291 banned row-level opacity dim). The 🔔/👁/★ glyphs remain
   * monochrome — colour is ONLY on the category icon at position 1.
   *
   * channelBadgeModel(c).color resolves to any user-set channel colour
   * first, then falls back to _identityColor → getAgentColor(norm); we
   * reuse it here so a channel's sidebar accent matches its pool chip
   * label colour and its topology label fill. */
  var accentColor = "";
  if (typeof channelBadgeModel === "function") {
    var m = channelBadgeModel(c);
    accentColor = (m && m.color) || "";
  }
  if (!accentColor && typeof getAgentColor === "function") {
    accentColor = getAgentColor(norm);
  }
  var accentStyle = accentColor
    ? ' style="--channel-accent:' + escapeHtml(accentColor) + '"'
    : "";
  return (
    divider +
    '<div class="channel-item ch-badge ch-badge-sidebar' +
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
    accentStyle +
    ' draggable="true">' +
    badgeInner +
    "</div>"
  );
}

/* Wire click/drag/context-menu handlers on every .channel-item currently in
 * chContainer. Pulled out of fetchStats so the main entry point stays under
 * the file-size budget without changing any observable behavior. */
export function _wireChannelItemHandlers(chContainer, prevSelected) {
  /* #293: enforce single-select hard invariant on restore. Even if
   * prevSelected contained multiple entries (from a stale DOM where
   * two rows both carried .selected — the regression this PR fixes),
   * we restore .selected to AT MOST ONE row, preferring the current
   * channel. Anything else is dropped on the floor. */
  var restoredOne = false;
  chContainer.querySelectorAll(".channel-item").forEach(function (el) {
    var elCh = el.getAttribute("data-channel");
    if (
      !restoredOne &&
      elCh &&
      prevSelected[elCh] &&
      (globalThis as any).currentChannel === elCh
    ) {
      el.classList.add("selected");
      restoredOne = true;
    } else {
      /* Defensive: make sure NO row carries .selected unless we just
       * added it above. Belt-and-braces against any stale DOM state. */
      el.classList.remove("selected");
    }
    /* msg#16979 — channel-card double-handler race.
     *
     * Star (.ch-pin), eye (.ch-eye), mute (.ch-mute) and watch (.ch-watch)
     * clicks are owned by the body-level capture-phase delegate in
     * channel-badge.ts (attachChannelBadgeHandlers). Per-row wiring
     * here duplicated the same _setChannelPref call on the same click,
     * causing a double-toggle that looked like "nothing happens" — the
     * second call inverted the optimistic update from the first (the
     * per-row bubble handler ran on the detached old element even after
     * the delegate tore down the DOM, and by that point _channelPrefs
     * already held the new value, so !curPref.is_* flipped it back).
     *
     * The delegate covers every surface that renders a channel badge
     * (sidebar row, pool chip, topology canvas), so the per-row
     * listeners are intentionally omitted here. */
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
      /* #284: channels are single-selection only. The legacy Ctrl/Cmd+Click
       * multi-select has been removed — any click replaces the current
       * selection with exactly this row.
       *
       * todo#305 / lead msg#15493: clicking the currently-selected row
       * is a NO-OP — there is always exactly one selected channel, and
       * re-clicking must not deselect. Previously this branch set the
       * channel to null (empty chat, no highlight); users reported it
       * as a defect ("sometimes no channel is selected at all"). */
      if ((globalThis as any).currentChannel !== ch) {
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
      /* todo#274 Part 1 + #293: single-select is the HARD invariant —
       * clear .selected across the ENTIRE sidebar (channel rows AND
       * DM agent-cards), not just this chContainer. Previously only
       * chContainer was cleared, which left a stale .selected on a
       * DM row when the user switched from a DM to a channel and
       * manifested as "two rows selected at once" (#293).
       *
       * todo#305: unconditionally re-select this row — the click
       * handler above no longer deselects on re-click, so the class
       * must always land back on this element after the cross-sidebar
       * clear. */
      document
        .querySelectorAll(".sidebar .channel-item.selected, .sidebar .dm-item.selected")
        .forEach(function (it) {
          it.classList.remove("selected");
        });
      el.classList.add("selected");
      if (typeof applyFeedFilter === "function") applyFeedFilter();
      fetchStats();
    });
  });
}
