/* activity-tab/grid-click.js — delegated click handler for the
 * overview grid: pin button, card expand, topology edge popover, pool
 * actions, pool chip selection, topology agent/channel clicks, action
 * bar. Helper wired from grid-delegation.js. */

function _ovgWireClick(grid) {
  grid.addEventListener("click", function (ev) {
    var pinBtn = ev.target.closest(".activity-pin-btn[data-pin-name]");
    if (pinBtn && grid.contains(pinBtn)) {
      ev.stopPropagation();
      var pname = pinBtn.getAttribute("data-pin-name");
      var nextPin = pinBtn.getAttribute("data-pin-next") === "true";
      var live = window.__lastAgents || [];
      for (var i = 0; i < live.length; i++) {
        if (live[i].name === pname) {
          live[i].pinned = nextPin;
          break;
        }
      }
      pinBtn.classList.toggle("activity-pin-on", nextPin);
      pinBtn.setAttribute("data-pin-next", nextPin ? "false" : "true");
      if (typeof togglePinAgent === "function") {
        togglePinAgent(pname, nextPin);
      } else {
        console.error(
          "togglePinAgent unavailable — pin click had no effect for",
          pname,
        );
      }
      return;
    }
    var card = ev.target.closest(".activity-card[data-agent]");
    if (card && grid.contains(card)) {
      /* ignore clicks that originate inside the inline-detail panel —
       * those should be handled by the detail's own widgets, not toggle
       * expand. */
      if (ev.target.closest(".activity-inline-detail")) return;
      var cname = card.getAttribute("data-agent");
      if (!cname) return;
      if (ev.shiftKey || ev.ctrlKey || ev.metaKey) {
        if (typeof addTag === "function") addTag("agent", cname);
        return;
      }
      _overviewExpanded = _overviewExpanded === cname ? null : cname;
      renderActivityTab();
      return;
    }
    /* Topology edge click → unsubscribe popover. Edges are bare <line>
     * elements inside <g class="topo-edges">; the wide invisible
     * .topo-edge-hit overlay is what actually receives the click (the
     * visible .topo-edge is pointer-events:none, decorative only).
     * Human→channel dashed guides get the same overlay (.topo-edge-hit-
     * human) but skip the popover — we don't want a "unsubscribe" on a
     * line between the signed-in human and a channel they already
     * joined deliberately. */
    var topoEdgeHit = ev.target.closest(".topo-edges line.topo-edge-hit");
    if (topoEdgeHit && grid.contains(topoEdgeHit)) {
      if (topoEdgeHit.classList.contains("topo-edge-hit-human")) return;
      if (ev.shiftKey || ev.ctrlKey || ev.metaKey) return;
      var eAgent = topoEdgeHit.getAttribute("data-agent");
      var eCh = topoEdgeHit.getAttribute("data-channel");
      if (eAgent && eCh) {
        ev.preventDefault();
        ev.stopPropagation();
        _topoShowEdgeMenu(eAgent, eCh, ev.clientX, ev.clientY);
        return;
      }
    }
    /* Pool Save button — identical to the sidebar's Save button
     * (same `data-action="save"` contract). Delegates to the shared
     * _memSaveActionHandler so both surfaces show the same "Pick an
     * M-slot first" hint when no slot is active. Handled before the
     * chip click block so this button doesn't also get read as a chip
     * click. 2026-04-20 pool/sidebar unification pass. */
    var poolSaveBtn = ev.target.closest(
      '.topo-pool-actions .sidebar-memory-actions button[data-action="save"]',
    );
    if (poolSaveBtn && grid.contains(poolSaveBtn)) {
      if (typeof _memSaveActionHandler === "function") {
        var _ok = _memSaveActionHandler(poolSaveBtn);
        if (_ok && typeof _sidebarMemoryRefreshBothSurfaces === "function") {
          _sidebarMemoryRefreshBothSurfaces();
        }
      }
      ev.stopPropagation();
      return;
    }
    /* Left-pool chip click: ctrl/meta = toggle membership in the pool
     * selection set; shift = range-select within the section; plain
     * click = clear + select only this chip. Drag-to-subscribe between
     * chips is handled by the mousedown/mouseup block further down.
     * Suppress the click that follows a just-completed drag so the
     * drop doesn't also mutate selection. */
    var poolChip = ev.target.closest(".topo-pool-chip");
    if (poolChip && grid.contains(poolChip)) {
      if (_topoDragState && _topoDragState.suppressClick) {
        _topoDragState.suppressClick = false;
        ev.stopPropagation();
        return;
      }
      var pcKind = poolChip.classList.contains("topo-pool-chip-channel")
        ? "channel"
        : "agent";
      var pcName = poolChip.getAttribute(
        pcKind === "channel" ? "data-channel" : "data-agent",
      );
      if (!pcName) return;
      /* Plain click on a HIDDEN chip = un-hide (the pool is the
       * canonical "bring it back" affordance). ywatanabe 2026-04-19:
       * "once hidden channels cannot be shown for good" / "are there
       * no interface to show once hidden channels???". Ctrl/meta
       * still toggles selection so multi-select can include hidden. */
      var prefHidden =
        pcKind === "channel" && (window._channelPrefs || {})[pcName]
          ? !!(window._channelPrefs[pcName] || {}).is_hidden
          : false;
      var isHidden =
        (pcKind === "agent" && _topoHidden.agents[pcName]) ||
        (pcKind === "channel" && _topoHidden.channels[pcName]) ||
        prefHidden;
      if (isHidden && !(ev.ctrlKey || ev.metaKey) && !ev.shiftKey) {
        if (typeof _topoUnhide === "function") _topoUnhide(pcKind, pcName);
        if (prefHidden && typeof _setChannelPref === "function") {
          _setChannelPref(pcName, { is_hidden: false });
        }
        _topoLastSig = "";
        if (typeof renderActivityTab === "function") renderActivityTab();
        ev.stopPropagation();
        return;
      }
      /* Plain click now toggles membership — the selection set is the
       * filter (logical AND across selected elements), so clicking a
       * chip just adds/removes that chip. Shift still isolates
       * ("select only this") for quick focus. Ctrl+click preserved
       * for muscle-memory users; does the same toggle. ywatanabe
       * 2026-04-19: "just simply on/off for each element and keep
       * such a state in filtering". */
      if (ev.shiftKey && !ev.altKey) {
        _topoPoolSelectOnly(pcKind, pcName);
        _topoPoolSelAnchor = { kind: pcKind, name: pcName };
      } else if (ev.altKey) {
        _topoPoolSelectRange(poolChip);
      } else {
        _topoPoolSelectToggle(pcKind, pcName);
        _topoPoolSelAnchor = { kind: pcKind, name: pcName };
      }
      _topoPoolSelectionPaint(grid);
      ev.stopPropagation();
      return;
    }
    /* Topology view — agent node click dispatch. Modifiers take
     * precedence over the 1/2/3-click timer:
     *   shift+click          → toggle multi-select membership
     *   ctrl/meta+click      → addTag (routes to Ctrl+K global search)
     *   plain 1-click        → drag source (handled on mousedown; click is a no-op)
     *   plain 2-click        → open DM with that agent
     *   plain 3-click        → toggle inline detail expand
     * The click that immediately follows a successful drag-drop is
     * suppressed so the drop doesn't also trigger expand. */
    var topoAgent = ev.target.closest(".topo-agent[data-agent]");
    if (topoAgent && grid.contains(topoAgent)) {
      if (ev.target.closest(".activity-inline-detail")) return;
      var tname = topoAgent.getAttribute("data-agent");
      if (!tname) return;
      if (ev.shiftKey) {
        _topoSelectToggle(tname);
        _topoLastSig = "";
        renderActivityTab();
        return;
      }
      if (ev.ctrlKey || ev.metaKey) {
        if (typeof addTag === "function") addTag("agent", tname);
        return;
      }
      /* Suppress click dispatched immediately after a successful drop
       * (prevents accidental expand after drag-release). */
      if (_topoDragState && _topoDragState.suppressClick) {
        _topoDragState.suppressClick = false;
        return;
      }
      _topoBumpClick(tname, ev.clientX, ev.clientY, "agent");
    }
    /* Channel node click counter — 2 = inline compose popup,
     * 3 = jump to Chat tab on this channel. ywatanabe 2026-04-19
     * "triple click a channel → show in Chat channel". */
    var topoChannel = ev.target.closest(".topo-channel[data-channel]");
    if (topoChannel && grid.contains(topoChannel)) {
      if (ev.target.closest(".activity-inline-detail")) return;
      var chName = topoChannel.getAttribute("data-channel");
      if (!chName) return;
      _topoBumpClick(chName, ev.clientX, ev.clientY, "channel");
    }
    /* Topology action-bar buttons (post / clear). These live outside
     * the SVG but inside `grid`, so the delegation catches them here. */
    var abBtn = ev.target.closest(".topo-actionbar-btn[data-topo-action]");
    if (abBtn && grid.contains(abBtn)) {
      ev.stopPropagation();
      var action = abBtn.getAttribute("data-topo-action");
      if (action === "clear") {
        _topoSelectClear();
        _topoLastSig = "";
        renderActivityTab();
      } else if (action === "post") {
        _openTopoGroupCompose(_topoSelectedNames());
      }
      return;
    }
  });
}
