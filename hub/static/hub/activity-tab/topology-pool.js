/* activity-tab/topology-pool.js — left-side agents + channels pool,
 * memory slot buttons, pool-action strip (Select All / None / M1..M5 / +Save). */

function _topoBuildPoolHtml(visible, channels) {
  /* Left-side pool — all agents and all channels as chips so the user
   * can see the full universe at a glance even when the canvas is
   * zoomed / cluttered. ywatanabe 2026-04-19: "place channels pool;
   * agents pool in the left side" / "so immediately create pool for
   * agents and channels!!!!". Click a chip → scroll its node into
   * view by re-centering the viewBox on it. */
  var poolAgentsHtml = visible
    .slice()
    .sort(function (a, b) {
      return (a.name || "").localeCompare(b.name || "");
    })
    .map(function (a) {
      var selCls = _topoPoolSelection.agents[a.name]
        ? " topo-pool-chip-selected"
        : "";
      /* todo#96: shared identity helper — color + display-name +
       * tooltip + icon HTML come from the same source as the sidebar
       * agent row and the canvas node. Replaces the ad-hoc "🤖" glyph
       * and the raw a.name tooltip with the unified agentIdentity()
       * cascade (image > emoji > text > snake SVG) and the
       * "<id> (<machine>)" hover text. */
      var _ident =
        typeof agentIdentity === "function"
          ? agentIdentity(a)
          : {
              displayName: a.name,
              color:
                typeof getAgentColor === "function"
                  ? getAgentColor(
                      typeof _colorKeyFor === "function"
                        ? _colorKeyFor(a)
                        : a.name,
                    )
                  : "#eaf1fb",
              tooltip: a.name,
              iconHtml: function () {
                return "\uD83E\uDD16";
              },
            };
      /* Liveness LEDs + pin glyph — mirrors the canvas agent node so
       * you can read ws/fn state straight from the pool without
       * looking at the graph. Classes match the list view
       * (.activity-led-ws-on/off, .activity-led-fn-<liveness>) so the
       * colors stay in lockstep with every other agent surface.
       * ywatanabe 2026-04-19: "Agents Pool > Should show indicators
       * and pin as well" (todo#84). */
      var pConnected = (a.status || "online") !== "offline";
      var pLiveness =
        a.liveness || a.status || (pConnected ? "online" : "offline");
      /* Always render the star slot so agent-name columns stay aligned
       * whether the agent is starred or not — same placeholder pattern
       * as the channel chip star/mute slots. ywatanabe 2026-04-19:
       * "we do not use pin at all; just use star". Class name
       * .topo-pool-chip-pin kept for CSS stability; glyph is now ★. */
      var pPin = a.pinned
        ? '<span class="topo-pool-chip-pin" title="starred">\u2605</span>'
        : '<span class="topo-pool-chip-pin topo-pool-chip-pin-off" aria-hidden="true"></span>';
      /* Color the NAME text, not a left-edge stripe. ywatanabe
       * 2026-04-19: "do not highlight left edge of cards; but update
       * colors of the agent text instead". */
      // Single source of truth — agent-badge.js. Same call lives in
      // app.js sidebar and the list-view row above. NEVER fork.
      return (
        '<div class="topo-pool-chip topo-pool-chip-agent' +
        selCls +
        '" data-agent="' +
        escapeHtml(a.name) +
        '" title="' +
        escapeHtml(_ident.tooltip) +
        '">' +
        renderAgentBadge(a, {
          iconSize: 12,
          extraClass: "topo-pool-chip-led",
        }) +
        "</div>"
      );
    })
    .join("");
  var poolChSet = {};
  channels.forEach(function (c) {
    poolChSet[c] = true;
  });
  Object.keys(window._channelPrefs || {}).forEach(function (c) {
    if (c && c.charAt(0) === "#") poolChSet[c] = true;
  });
  var _poolChPrefs = window._channelPrefs || {};
  var poolChannelsHtml = Object.keys(poolChSet)
    .sort()
    .map(function (c) {
      var selCls = _topoPoolSelection.channels[c]
        ? " topo-pool-chip-selected"
        : "";
      /* Single source of truth — channel-badge.js renderChannelBadgeHtml.
       * Same call surface as the sidebar row and canvas node so chip
       * ↔ row ↔ node UI stays identical (ywatanabe 2026-04-20: "ALL
       * channel badge MUST have the SAME UI and functionalities").
       * Star/eye/mute clicks route through the body-level delegation
       * wired in attachChannelBadgeHandlers(). */
      var _tooltip =
        typeof channelIdentity === "function"
          ? channelIdentity(c).tooltip || c
          : c;
      var badgeInner =
        typeof renderChannelBadgeHtml === "function"
          ? renderChannelBadgeHtml(c, {
              context: "pool",
              showEye: true,
              showUnread: false,
              iconSize: 14,
            })
          : "";
      return (
        '<div class="topo-pool-chip topo-pool-chip-channel ch-badge ch-badge-pool' +
        selCls +
        '" data-channel="' +
        escapeHtml(c) +
        '" title="' +
        escapeHtml(_tooltip) +
        '">' +
        badgeInner +
        "</div>"
      );
    })
    .join("");
  /* Pool action strip — Select All / Deselect All / M1..M5 / +Save.
   * Memory slot chips show filled state (green dot) when occupied;
   * click to recall, shift-click to overwrite with the current
   * selection, right-click to delete. The +Save button saves to the
   * next free slot (or does nothing once all 5 are full — user can
   * shift-click an existing slot to overwrite). todo#79
   * "Pools as filters ... Select All / Deselect All / Memory 1,2,...". */
  var memBtnsHtml = "";
  for (var _ms = 1; _ms <= _TOPO_POOL_MEM_MAX; _ms++) {
    var _mem = _topoPoolMemories[String(_ms)];
    var _memCount = _mem
      ? (_mem.agents || []).length + (_mem.channels || []).length
      : 0;
    var _memHidCount =
      _mem && _mem.hidden
        ? (_mem.hidden.agents || []).length +
          (_mem.hidden.channels || []).length
        : 0;
    var _memFilterActive = !!(
      _mem &&
      _mem.filter &&
      ((_mem.filter.input && _mem.filter.input.length) ||
        (Array.isArray(_mem.filter.tags) && _mem.filter.tags.length))
    );
    var _memLabel = _mem && _mem.label ? String(_mem.label) : "";
    /* Tooltip surfaces the full snapshot composition so users can tell
     * slots apart without recalling them. todo#98. */
    var _memTitle;
    if (_mem) {
      var parts = [];
      parts.push(_memCount + " selected");
      if (_memHidCount) parts.push(_memHidCount + " hidden");
      if (_memFilterActive) parts.push("filter");
      _memTitle =
        "Recall M" +
        _ms +
        (_memLabel ? " — " + _memLabel : "") +
        " (" +
        parts.join(", ") +
        "). Shift+click to overwrite, right-click to rename or clear.";
    } else {
      _memTitle =
        "M" +
        _ms +
        " (empty). Click +Save or shift-click this slot to snapshot the current view.";
    }
    /* Button face: keep "M1".."M5" when empty/unlabeled, or show the
     * user-chosen label when present. Truncate aggressively so a long
     * label never blows out the compact action row. Filled unlabeled
     * slots get a small count suffix ("M1·3") so users can see at a
     * glance which slots hold data and how much — the color alone was
     * too subtle (2026-04-19 user report: "memory saving is not
     * working yet"). */
    var _memFace;
    if (_memLabel) {
      _memFace =
        _memLabel.length > 6 ? _memLabel.slice(0, 5) + "\u2026" : _memLabel;
    } else if (_mem && _memCount > 0) {
      _memFace = "M" + _ms + "\u00b7" + _memCount;
    } else {
      _memFace = "M" + _ms;
    }
    memBtnsHtml +=
      '<button type="button" class="topo-pool-mem-btn' +
      (_mem ? " topo-pool-mem-btn-filled" : "") +
      (_memLabel ? " topo-pool-mem-btn-labeled" : "") +
      '" data-mem-slot="' +
      _ms +
      '" title="' +
      escapeHtml(_memTitle) +
      '">' +
      escapeHtml(_memFace) +
      "</button>";
  }
  var _selCountInit = _topoPoolSelectionSize();
  var poolActions =
    '<div class="topo-pool-actions">' +
    '<div class="topo-pool-actions-row">' +
    '<button type="button" class="topo-pool-act-btn" data-pool-action="select-all" title="Select every visible chip">All</button>' +
    '<button type="button" class="topo-pool-act-btn" data-pool-action="deselect-all" title="Clear pool selection (shows all)">None</button>' +
    '<span class="topo-pool-selcount">' +
    (_selCountInit === 0 ? "" : _selCountInit + " selected") +
    "</span>" +
    "</div>" +
    '<div class="topo-pool-actions-row topo-pool-mem-row">' +
    memBtnsHtml +
    '<button type="button" class="topo-pool-mem-save" data-pool-action="save-next" title="Save current selection to next free memory slot">+</button>' +
    "</div>" +
    "</div>";
  var pool =
    '<div class="topo-pool">' +
    poolActions +
    '<div class="topo-pool-section"><div class="topo-pool-title">Agents</div>' +
    poolAgentsHtml +
    "</div>" +
    '<div class="topo-pool-section"><div class="topo-pool-title">Channels</div>' +
    poolChannelsHtml +
    "</div>" +
    "</div>";
  return pool;
}
