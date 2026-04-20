// @ts-nocheck
// Migrated classic-script file. Types intentionally loose during
// the big-bang JS-to-TS bundle migration. Narrow later, per-file.
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
    /* Right-click on a memory slot button → rename (or clear by entering
     * an empty name). todo#98: memory slots now snapshot the full filter
     * state, so giving them a human label makes them actually usable as
     * presets. Cancel = no change, "" = clear/delete. Empty slots are
     * a no-op on right-click (nothing to rename). todo#79 "Memory 1,2,…
     * (to keep the same criteria for selected)" is preserved — clearing
     * still works by entering an empty label. */
    var memBtnCtx = ev.target.closest(".topo-pool-mem-btn[data-mem-slot]");
    if (memBtnCtx && grid.contains(memBtnCtx)) {
      var slotStrCtx = memBtnCtx.getAttribute("data-mem-slot");
      var slotCtx = parseInt(slotStrCtx, 10);
      if (slotCtx >= 1 && slotCtx <= _TOPO_POOL_MEM_MAX) {
        ev.preventDefault();
        ev.stopPropagation();
        var existingMem = _topoPoolMemories[String(slotCtx)];
        if (existingMem) {
          var curLabel =
            existingMem.label && typeof existingMem.label === "string"
              ? existingMem.label
              : "";
          /* prompt() is synchronous and ugly but matches the "one-pass,
           * don't break existing" constraint — no modal plumbing needed. */
          var answer = null;
          try {
            answer = window.prompt(
              "Rename M" + slotCtx + " (leave empty to clear the slot):",
              curLabel,
            );
          } catch (_pe) {
            answer = null;
          }
          if (answer === null) return; /* user hit Cancel */
          var trimmed = String(answer).trim();
          if (trimmed === "") {
            _topoPoolMemoryDelete(slotCtx);
          } else {
            _topoPoolMemoryRename(slotCtx, trimmed);
          }
          _topoLastSig = "";
          if (typeof renderActivityTab === "function") renderActivityTab();
        }
        return;
      }
    }
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
