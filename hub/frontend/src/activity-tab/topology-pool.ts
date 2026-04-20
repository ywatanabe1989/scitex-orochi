// @ts-nocheck
/* activity-tab/topology-pool.js — left-side agents + channels pool,
 * memory slot buttons, pool-action strip (Select All / None / M1..M5 / +Save). */

function _topoBuildPoolHtml(visible, channels) {
  /* ywatanabe 2026-04-21: "drop the pools themselves (hide them); we
   * have the sidebar and it is enough; no duplication please". The
   * sidebar Agents/Channels/Filtering sections provide every operation
   * the canvas pool used to. Return an empty, display:none placeholder
   * so downstream code that queries `.topo-pool` / `.topo-pool-chip-*`
   * selectors doesn't blow up with null refs. If we confirm nothing
   * depends on the pool being in the DOM we can return "" later. */
  if (visible && channels) {
    /* Keep the function signature live; caller still passes args. */
  }
  return '<div class="topo-pool" style="display:none"></div>';
}

/* Legacy pool builder — kept for reference in case a future change
 * wants the in-canvas pool back. Never invoked from runtime because
 * _topoBuildPoolHtml above short-circuits. */
function _topoBuildPoolHtmlLegacy(visible, channels) {
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
  /* Pool memory control — single <select> dropdown + Save button.
   * EXACT same structure as the sidebar Memory section (see
   * dashboard.html lines ~110-123 and app/sidebar-memory.js), so both
   * surfaces read/write the same _topoPoolMemories + _topoActiveMemSlot
   * state and auto-sync. The options are populated by
   * sidebar-memory.js::renderSidebarMemory (which mirrors into both
   * selects). Replaces the legacy M1-M5 chip row + All/None buttons
   * (2026-04-20 unification pass — ywatanabe: "the pool strip must
   * use the exact same control as the sidebar").
   *
   * NOTE: the dropdown `id="topo-pool-mem-select"` is distinct from the
   * sidebar's `sidebar-mem-select` so both can coexist in the DOM.
   * Both carry class `sidebar-mem-select` so the existing CSS in
   * app/sidebar-memory.css styles both. */
  /* Pool memory dropdown + Save button are DUPLICATED in the sidebar
   * FILTERING section (ywatanabe 2026-04-21: "hide them first; maybe
   * we don't need them as we have sidebar"). Rendered but display:none
   * so the sidebar-memory.js helpers that still populate
   * #topo-pool-mem-select don't crash. Remove entirely later if the
   * sidebar-only layout confirms correct. */
  var poolActions =
    '<div class="topo-pool-actions" style="display:none">' +
    '<div class="sidebar-memory-picker">' +
    '<select id="topo-pool-mem-select" class="sidebar-mem-select" title="Switch active memory slot. + Create new takes the next free slot."></select>' +
    "</div>" +
    '<div class="sidebar-memory-actions">' +
    '<button type="button" class="sidebar-mem-btn sidebar-mem-save" data-action="save" title="Save current selection to the active memory slot">Save</button>' +
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
