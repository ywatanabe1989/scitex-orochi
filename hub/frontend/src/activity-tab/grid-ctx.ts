// @ts-nocheck
/* activity-tab/grid-ctx.js — delegated contextmenu (right-click)
 * handler for the overview grid: memory slot rename/delete, edge
 * unsubscribe popover, channel/agent/pool context menus. Helper wired
 * from grid-delegation.js. */

function _ovgWireContextmenu(grid) {
  /* Delegated right-click on overview cards, topology agent nodes, and
   * topology channel diamonds → open the entity-specific context menu
   * from app.js. Survives innerHTML rewrites. ywatanabe 2026-04-19:
   * "right click should have menus based on the entity clicked;
   * (channel, agent)". Channel menu resolved first so the shared
   * .topo-channel + .topo-agent hit-test order doesn't misroute. */
  grid.addEventListener("contextmenu", function (ev) {
    if (ev.shiftKey) return;
    /* NOTE: the legacy M1-M5 chip right-click rename flow used to live
     * here. The pool now exposes memory via a <select> dropdown that
     * mirrors the sidebar — rename/clear is handled by the sidebar's
     * own contextmenu on the sidebar chips (legacy flow still present
     * for the chip row template variant). 2026-04-20 pool/sidebar
     * unification pass. */
    /* Right-click on an agent→channel edge → same unsubscribe popover
     * as the left-click path. Channel/agent nodes are resolved by later
     * branches so the order here matters — edge check first, since a
     * line never overlaps a diamond/circle hit box. Hit overlay is the
     * event target (visible .topo-edge is pointer-events:none); skip
     * human→channel dashed edges. */
    var topoEdgeHitCtx = ev.target.closest(".topo-edges line.topo-edge-hit");
    if (topoEdgeHitCtx && grid.contains(topoEdgeHitCtx)) {
      if (!topoEdgeHitCtx.classList.contains("topo-edge-hit-human")) {
        var eAgent = topoEdgeHitCtx.getAttribute("data-agent");
        var eCh = topoEdgeHitCtx.getAttribute("data-channel");
        if (eAgent && eCh) {
          ev.preventDefault();
          ev.stopPropagation();
          _topoShowEdgeMenu(eAgent, eCh, ev.clientX, ev.clientY);
          return;
        }
      }
    }
    var topoCh = ev.target.closest(".topo-channel[data-channel]");
    if (topoCh && grid.contains(topoCh)) {
      if (typeof _showChannelCtxMenu !== "function") return;
      var ch = topoCh.getAttribute("data-channel");
      if (!ch) return;
      ev.preventDefault();
      ev.stopPropagation();
      _showChannelCtxMenu(ch, ev.clientX, ev.clientY);
      return;
    }
    /* Left-pool chips — channel chip first (checked before agent chip
     * because a single chip element carries exactly one of the two
     * class+data-attr pairs, so the order is informational, not a
     * hit-test priority). ywatanabe 2026-04-19: "right-click on a pool
     * chip should open the same menu as right-clicking the canvas
     * node". Without this branch the browser falls through to its
     * native Copy/Search/AdBlock context menu. */
    var poolChipCh = ev.target.closest(".topo-pool-chip-channel[data-channel]");
    if (poolChipCh && grid.contains(poolChipCh)) {
      if (typeof _showChannelCtxMenu !== "function") return;
      var pcCh = poolChipCh.getAttribute("data-channel");
      if (!pcCh) return;
      ev.preventDefault();
      ev.stopPropagation();
      _showChannelCtxMenu(pcCh, ev.clientX, ev.clientY);
      return;
    }
    var poolChipAg = ev.target.closest(".topo-pool-chip-agent[data-agent]");
    if (poolChipAg && grid.contains(poolChipAg)) {
      if (typeof _showAgentContextMenu !== "function") return;
      var pcAg = poolChipAg.getAttribute("data-agent");
      if (!pcAg) return;
      ev.preventDefault();
      ev.stopPropagation();
      _showAgentContextMenu(pcAg, ev.clientX, ev.clientY);
      return;
    }
    var card = ev.target.closest(".activity-card[data-agent]");
    var topo = ev.target.closest(".topo-agent[data-agent]");
    var host = card || topo;
    if (!host || !grid.contains(host)) return;
    var name = host.getAttribute("data-agent");
    if (!name) return;
    if (typeof _showAgentContextMenu !== "function") return;
    ev.preventDefault();
    ev.stopPropagation();
    _showAgentContextMenu(name, ev.clientX, ev.clientY);
  });
}
