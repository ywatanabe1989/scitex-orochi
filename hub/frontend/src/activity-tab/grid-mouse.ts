/* activity-tab/grid-mouse.js — delegated dblclick / mousedown /
 * mousemove / mouseup / window.blur handlers for the overview grid.
 * Implements the drag-to-subscribe + optimistic edge add + canvas
 * drag-to-reposition gestures. Helper wired from grid-delegation.js. */


function _ovgWireMouse(grid) {
  /* Native dblclick fallback — bumps the counter to 2 so the same
   * _topoFlushClick codepath opens the DM. Prevents the grid-level
   * dblclick handler (which resets zoom) from also firing when the
   * target is an agent node. */
  grid.addEventListener("dblclick", function (ev) {
    var topoAgent = ev.target.closest(".topo-agent[data-agent]");
    if (!topoAgent || !grid.contains(topoAgent)) return;
    var tname = topoAgent.getAttribute("data-agent");
    if (!tname) return;
    ev.stopPropagation();
    /* The two clicks that made up the dblclick already bumped the
     * counter via the click handler, so we don't need to bump again —
     * but if the counter was flushed (rare: very fast dblclick with
     * synthesized click events not firing twice), ensure count >= 2. */
    if (!_topoClickState || _topoClickState.name !== tname) {
      _openAgentDm(tname);
    } else if (_topoClickState.count < 2) {
      _topoClickState.count = 2;
    }
  });
  /* Drag-to-subscribe — mousedown on an agent OR channel node (canvas
   * or left-pool chip) starts a drag session. This coexists with
   * _wireTopoZoomPan because that handler short-circuits when the
   * target is .topo-agent/.topo-channel; pool chips live outside the
   * SVG so there's no zoom-pan conflict there. */
  grid.addEventListener("mousedown", function (ev) {
    if (ev.button !== 0) return;
    if (ev.shiftKey || ev.ctrlKey || ev.metaKey) return;
    /* Canvas SVG is still the ghost host (pool chips live in HTML, but
     * the ghost is an SVG <text> element, so we need the SVG handle
     * regardless of where the drag originated). */
    var svg = grid.querySelector(".topo-svg");
    var agentNode = ev.target.closest(".topo-agent[data-agent]");
    var channelNode = ev.target.closest(".topo-channel[data-channel]");
    var poolChip = ev.target.closest(".topo-pool-chip");
    var source = null;
    var kind = null;
    var name = null;
    if (agentNode || channelNode) {
      /* Require the canvas SVG context so zoom-pan doesn't fight us. */
      if (!ev.target.closest(".topo-svg")) return;
      source = "canvas";
      kind = agentNode ? "agent" : "channel";
      name = agentNode
        ? agentNode.getAttribute("data-agent")
        : channelNode.getAttribute("data-channel");
    } else if (poolChip) {
      source = "pool";
      kind = poolChip.classList.contains("topo-pool-chip-channel")
        ? "channel"
        : "agent";
      name = poolChip.getAttribute(
        kind === "channel" ? "data-channel" : "data-agent",
      );
      /* Block native text-selection that would otherwise sweep across
       * the pool + adjacent canvas elements as soon as the mouse moves.
       * CSS user-select:none covers the chip itself, but the selection
       * can still start from the mousedown target and extend into
       * siblings; preventDefault here is what actually cancels it.
       * ywatanabe 2026-04-19: "dragging a pool chip wrongly text-
       * selects adjacent elements". */
      ev.preventDefault();
    } else {
      return;
    }
    if (!name || !svg) return;
    /* If the pressed chip is part of the current pool selection, drag
     * the whole selection (multi-subscribe on drop). Otherwise drag
     * only this single name. Canvas-originated drags always drag just
     * the one node (the canvas selection is a separate affordance). */
    var items = [{ kind: kind, name: name }];
    if (source === "pool" && _topoPoolSelectionHas(kind, name)) {
      items = [];
      Object.keys(_topoPoolSelection.agents).forEach(function (n) {
        items.push({ kind: "agent", name: n });
      });
      Object.keys(_topoPoolSelection.channels).forEach(function (n) {
        items.push({ kind: "channel", name: n });
      });
    }
    _topoDragState = {
      svg: svg,
      source: source,
      kind: kind,
      name: name,
      items: items,
      startX: ev.clientX,
      startY: ev.clientY,
      ghost: null,
      lastDrop: null,
      moved: false,
      suppressClick: false,
    };
  });
  grid.addEventListener("mousemove", function (ev) {
    var s = _topoDragState;
    if (!s) return;
    var dx = ev.clientX - s.startX;
    var dy = ev.clientY - s.startY;
    if (!s.moved && dx * dx + dy * dy < 16) return; /* 4px threshold */
    s.moved = true;
    /* Spawn ghost once we cross the threshold. Multi-item drags show a
     * compact "N items" label; single-item drags keep the verbose
     * "→ subscribe <name>" style. Which kinds the bundle contains
     * determines the arrow direction. ywatanabe 2026-04-19: "when
     * an agent moved, it must be moved there simply no need for the
     * → subscribe ghost; they should subscribe only when destination
     * hits a channel" — handled downstream via drop-target validation,
     * not the ghost label. */
    if (!s.ghost) {
      var p0 = _topoSvgPoint(s.svg, ev.clientX, ev.clientY);
      var label;
      if (s.items && s.items.length > 1) {
        var nA = 0;
        var nC = 0;
        for (var k = 0; k < s.items.length; k++) {
          if (s.items[k].kind === "agent") nA++;
          else nC++;
        }
        var parts = [];
        if (nA) parts.push(nA + " agent" + (nA === 1 ? "" : "s"));
        if (nC) parts.push(nC + " channel" + (nC === 1 ? "" : "s"));
        label = "\u2192 " + parts.join(" + ");
      } else {
        label = s.name;
      }
      s.ghost = _topoSpawnGhost(s.svg, label, p0.x + 8, p0.y - 8);
    }
    var p = _topoSvgPoint(s.svg, ev.clientX, ev.clientY);
    s.ghost.setAttribute("x", (p.x + 8).toFixed(1));
    s.ghost.setAttribute("y", (p.y - 8).toFixed(1));
    /* Hover highlight. Valid target = opposite-kind node, either on
     * canvas (.topo-channel / .topo-agent) or in the pool (.topo-pool-
     * chip-channel / .topo-pool-chip-agent). Bundles of mixed kinds
     * accept both — whichever we hit first is valid because we'll
     * filter per-item on drop. */
    var haveAgent = false;
    var haveChannel = false;
    if (s.items && s.items.length) {
      for (var ii = 0; ii < s.items.length; ii++) {
        if (s.items[ii].kind === "agent") haveAgent = true;
        else haveChannel = true;
      }
    } else {
      haveAgent = s.kind === "agent";
      haveChannel = s.kind === "channel";
    }
    var target = null;
    var stack = document.elementsFromPoint
      ? document.elementsFromPoint(ev.clientX, ev.clientY)
      : [];
    for (var i = 0; i < stack.length; i++) {
      var el = stack[i];
      var chHit =
        el.closest &&
        (el.closest(".topo-channel[data-channel]") ||
          el.closest(".topo-pool-chip-channel[data-channel]"));
      var agHit =
        el.closest &&
        (el.closest(".topo-agent[data-agent]") ||
          el.closest(".topo-pool-chip-agent[data-agent]"));
      /* Don't self-target: the chip we started the drag on must not
       * count as a drop target. */
      if (agHit && s.source === "pool" && s.kind === "agent") {
        var agN = agHit.getAttribute("data-agent");
        if (s.items && s.items.length === 1 && agN === s.name) agHit = null;
      }
      if (chHit && s.source === "pool" && s.kind === "channel") {
        var chN = chHit.getAttribute("data-channel");
        if (s.items && s.items.length === 1 && chN === s.name) chHit = null;
      }
      if (haveAgent && chHit) {
        target = chHit;
        break;
      }
      if (haveChannel && agHit) {
        target = agHit;
        break;
      }
    }
    if (s.lastDrop !== target) {
      if (s.lastDrop) s.lastDrop.classList.remove("topo-drop-target");
      if (target) target.classList.add("topo-drop-target");
      s.lastDrop = target;
      /* Update ghost label to reflect intent: over a valid target we
       * show the subscribe/read arrow, off-target we show just the
       * name so the drag reads as repositioning. */
      if (s.ghost) {
        var tgtLabel = "";
        if (target && s.kind === "agent") {
          tgtLabel = " → " + (target.getAttribute("data-channel") || "");
        } else if (target && s.kind === "channel") {
          tgtLabel = " → " + (target.getAttribute("data-agent") || "");
        }
        s.ghost.textContent = s.name + tgtLabel;
      }
    }
  });
  grid.addEventListener("mouseup", function (ev) {
    var s = _topoDragState;
    if (!s) return;
    var target = s.lastDrop;
    if (s.moved && target) {
      /* Optimistic: mutate __lastAgents so the channel membership
       * renders into the topology on the very next re-render, before
       * the server round-trip completes. Backend-authoritative state
       * still arrives via fetchAgentsThrottled() called inside
       * _agentSubscribe. */
      function _optimisticAdd(agentName, channel) {
        var live = window.__lastAgents || [];
        for (var i = 0; i < live.length; i++) {
          if (live[i].name === agentName) {
            var chs = Array.isArray(live[i].channels)
              ? live[i].channels.slice()
              : [];
            if (chs.indexOf(channel) === -1) chs.push(channel);
            live[i].channels = chs;
            break;
          }
        }
      }
      /* Resolve the drop target. Prefer canvas node, fall back to pool
       * chip. Both carry data-agent / data-channel attributes. */
      var targetCh = target.getAttribute("data-channel");
      var targetAg = target.getAttribute("data-agent");
      /* Bundle subscribes: loop each source item against the target.
       * Agents-in-bundle + channel-target ⇒ subscribe each agent.
       * Channels-in-bundle + agent-target ⇒ subscribe target to each.
       * Mixed bundles handle both branches in one drop. */
      var items =
        s.items && s.items.length ? s.items : [{ kind: s.kind, name: s.name }];
      var subscribedAgentsOnCh = 0;
      var subscribedChsOnAg = 0;
      for (var ix = 0; ix < items.length; ix++) {
        var it = items[ix];
        if (it.kind === "agent" && targetCh) {
          if (typeof _agentSubscribe === "function") {
            _topoStickyEdges[_topoStickyKey(it.name, targetCh)] = true;
            _optimisticAdd(it.name, targetCh);
            _agentSubscribe(it.name, targetCh, "read-write");
            subscribedAgentsOnCh++;
          }
        } else if (it.kind === "channel" && targetAg) {
          if (typeof _agentSubscribe === "function") {
            _topoStickyEdges[_topoStickyKey(targetAg, it.name)] = true;
            _optimisticAdd(targetAg, it.name);
            _agentSubscribe(targetAg, it.name, "read-only");
            subscribedChsOnAg++;
          }
        }
      }
      if (subscribedAgentsOnCh + subscribedChsOnAg > 0) {
        if (subscribedAgentsOnCh === 1 && subscribedChsOnAg === 0) {
          /* Single-agent → single-channel: keep the existing toast. */
          _topoShowSubscribeToast(items[0].name, targetCh, "read-write");
        } else if (subscribedAgentsOnCh === 0 && subscribedChsOnAg === 1) {
          _topoShowSubscribeToast(targetAg, items[0].name, "read-only");
        } else {
          /* Bundle drop — summary toast per user spec. */
          if (typeof _showMiniToast === "function") {
            if (subscribedAgentsOnCh > 0) {
              _showMiniToast(
                "Subscribed " +
                  subscribedAgentsOnCh +
                  " agent" +
                  (subscribedAgentsOnCh === 1 ? "" : "s") +
                  " \u2192 " +
                  targetCh,
                "ok",
              );
            }
            if (subscribedChsOnAg > 0) {
              _showMiniToast(
                "Subscribed " +
                  targetAg +
                  " \u2192 " +
                  subscribedChsOnAg +
                  " channel" +
                  (subscribedChsOnAg === 1 ? "" : "s"),
                "ok",
              );
            }
          }
        }
        /* Clear pool selection after a bundle subscribe so the next
         * drag isn't an accidental re-apply. */
        if (s.source === "pool" && items.length > 1) _topoPoolSelectClear();
        _topoLastSig = ""; /* force re-render with new edges */
        renderActivityTab();
      }
    }
    /* Canvas drag-to-reposition — if the drag started from a canvas
     * .topo-agent/.topo-channel node (not a pool chip) and was dropped
     * on empty SVG space (no valid subscribe target, no shift/ctrl/
     * meta), pin the node at the drop coordinate via a manual position
     * override. Additive path: does not disturb subscribe-drag (which
     * set target) or rectangle-zoom (handled by _wireTopoZoomPan with
     * a short-circuit on .topo-agent/.topo-channel targets).
     * ywatanabe 2026-04-19: canvas drag should also allow the user to
     * rearrange the topology freely. */
    if (s.moved && !target && s.source === "canvas" && s.kind && s.name) {
      var _dropP = _topoSvgPoint(s.svg, ev.clientX, ev.clientY);
      /* Keep drops strictly inside the SVG viewport — elementsFromPoint
       * wouldn't have picked the SVG at all if the cursor left it, so
       * this is mostly defensive against edge-case negative coords. */
      if (_dropP && isFinite(_dropP.x) && isFinite(_dropP.y)) {
        _topoSetManualPosition(s.kind, s.name, _dropP.x, _dropP.y);
        renderActivityTab();
      }
    }
    if (s.moved) {
      /* Any drag motion → suppress the trailing synthetic click so it
       * doesn't trigger the single/triple dispatcher. We keep the state
       * around for one tick so the click handler sees suppressClick,
       * then tear it down. */
      s.suppressClick = true;
      _topoClearDrop();
      /* Fade the ghost out over 250ms instead of hard-removing — the
       * babble just "evaporates" instead of popping. ywatanabe
       * 2026-04-19: "babble should disappear soon with animation". */
      if (s.ghost) {
        var ghost = s.ghost;
        ghost.style.transition = "opacity 0.25s ease-out";
        ghost.style.opacity = "0";
        setTimeout(function () {
          if (ghost.parentNode) ghost.parentNode.removeChild(ghost);
        }, 280);
        s.ghost = null;
      }
      setTimeout(function () {
        if (_topoDragState === s) _topoDragState = null;
      }, 0);
    } else {
      _topoCleanupDrag();
    }
  });
  /* Cancel on window blur / escape. */
  window.addEventListener("blur", _topoCleanupDrag);
}
