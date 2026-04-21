// @ts-nocheck
import { _addDragAndDrop } from "./agent-actions";
import { _channelPrefs } from "./members";
import { _buildRenderRows, _renderChannelRowHtml, _renderFolderRowHtml, _wireChannelItemHandlers } from "./sidebar-channel-tree";
import { apiUrl } from "./utils";
import { updateChannelUnreadBadges } from "./websocket";

/* Channel-tree render + per-row handler helpers live in
 * sidebar-channel-tree.js (loaded before this file in dashboard.html).
 * fetchStats() is the public entry point called from init.js and the
 * websocket / interval refresh paths. */

export async function fetchStats() {
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
    /* #284: channels are single-select only. prevSelected keeps the one
     * currently-selected row marked .selected across DOM re-renders so the
     * selection indicator doesn't flicker mid-refresh. (The legacy Ctrl+Click
     * multi-select — #274 Part 2 — has been removed for channels.) */
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
    var _renderRows = _buildRenderRows(
      displayChannels,
      _channelPrefs,
      _treeCollapsed,
    );
    var _rowCtx = {
      firstHiddenIdx: firstHiddenIdx,
      currentChannel: (globalThis as any).currentChannel,
    };
    chContainer.innerHTML = _renderRows
      .map(function (row) {
        return row.type === "folder"
          ? _renderFolderRowHtml(row)
          : _renderChannelRowHtml(row, _rowCtx);
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
    _wireChannelItemHandlers(chContainer, prevSelected);
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
