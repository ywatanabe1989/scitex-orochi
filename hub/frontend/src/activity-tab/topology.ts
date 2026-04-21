// @ts-nocheck
import { _fetchActivityDetail, _refreshTopoPerms } from "./data";
import { _renderActivityAgentDetail } from "./detail";
import { _wireOverviewGridDelegation } from "./grid-delegation";
import { _topoPoolApplyCanvasFilter, _topoPoolSelectionPaint, _topoSelectedNames } from "./multiselect";
import { _topoSeekHeatRefresh, _topoSeekUpdateUI, _topoSeekbarHtml, _wireTopoSeekbar } from "./seekbar";
import { _topoApplyStickyEdges, _topoManualKey, _topoManualPositions } from "./state";
import { _topoBuildEdgesHtml } from "./topology-edges";
import { _topoBuildAgentsSvg, _topoBuildChannelsSvg, _topoBuildHumanSvg } from "./topology-nodes";
import { _topoBuildPoolHtml } from "./topology-pool";
import { _topoSignature } from "./topology-signature";
import { _isDeadAgent } from "./utils";
import { _wireTopoZoomPan } from "./zoompan";
import { _channelPrefs } from "../app/members";
import { escapeHtml, userName } from "../app/utils";

/* activity-tab/topology.js — canvas topology renderer.
 * _renderActivityTopology: filter visible agents, compute ring layout,
 * emit edges + channel diamonds + agent pills + human node, autofit
 * viewBox, attach pool + seekbar + action-bar, wire zoom/pan/seek,
 * re-assert pool filter. */


export function _renderActivityTopology(visible, grid) {
  _topoApplyStickyEdges();
  /* Filter out agents the user hid via right-click (session-only via
   * _topoHidden) OR via the persistent 👁 eye on the agent card (Task 7,
   * AgentProfile.is_hidden — sticks across sessions). Edges involving
   * hidden agents collapse automatically because they're dropped from
   * the visible loop. Human node is protected inside _topoHide and
   * never has is_hidden on its payload. */
  visible = visible.filter(function (a) {
    if ((globalThis as any)._topoHidden.agents[a.name]) return false;
    /* todo#305 Task 7 (lead msg#15548): mirror channel-hidden topo
     * semantics — hidden agents are DROPPED from the canvas render
     * (not dimmed in place). Consistent with how channels hidden via
     * .ch-eye disappear from the topology. */
    if (a.is_hidden) return false;
    /* Dead agents render only when pinned (kept as ghost/shadow);
     * unpinned dead agents are dropped entirely from the canvas. */
    if (_isDeadAgent(a) && !a.pinned) return false;
    return true;
  });
  var sig = _topoSignature(visible);
  var existingSvg = grid.querySelector(".topo-svg");
  if (
    existingSvg &&
    sig === (globalThis as any)._topoLastSig &&
    (globalThis as any)._overviewExpanded === (globalThis as any)._topoLastExpanded
  ) {
    /* Nothing structurally changed — the existing SVG is still
     * accurate. Skip the full rebuild; just refresh the inline detail
     * panel if one is open (its contents DO change on heartbeat). */
    if ((globalThis as any)._overviewExpanded) {
      var agent0 = (window.__lastAgents || []).find(function (x) {
        return x.name === (globalThis as any)._overviewExpanded;
      });
      var inlineBox0 = grid.querySelector(
        '.activity-inline-detail[data-detail-for="' +
          String((globalThis as any)._overviewExpanded).replace(/"/g, '\\"') +
          '"]',
      );
      if (agent0 && inlineBox0) {
        _renderActivityAgentDetail(agent0, inlineBox0);
      }
    }
    /* Re-assert pool filter on every heartbeat so newly-born nodes
     * that slip in without changing the signature (rare but possible)
     * still get the correct dim treatment. */
    _topoPoolApplyCanvasFilter(grid);
    return;
  }
  (globalThis as any)._topoLastSig = sig;
  (globalThis as any)._topoLastExpanded = (globalThis as any)._overviewExpanded;
  /* Collect channels referenced by at least one visible agent, minus
   * DMs (implicit per-agent; not interesting in a topology view). */
  var chSet = {};
  visible.forEach(function (a) {
    (a.channels || []).forEach(function (c) {
      if (!c || c.indexOf("dm:") === 0) return;
      chSet[c] = true;
    });
  });
  /* Also include every workspace channel from _channelPrefs (the
   * sidebar channel list) so zero-subscriber channels still appear
   * as connectable nodes — ywatanabe 2026-04-19 "channels must be
   * there all the time even with 0 subscribers to allow connection".
   */
  if (typeof _channelPrefs !== "undefined" && _channelPrefs) {
    Object.keys(_channelPrefs).forEach(function (c) {
      if (!c || c.indexOf("dm:") === 0) return;
      chSet[c] = true;
    });
  }
  /* Filter out channels the user hid via channel-ctx-menu. ywatanabe
   * 2026-04-19: "hide channel does not hide as well" — the sidebar
   * respected is_hidden but the topology did not. */
  var _chPrefs = window._channelPrefs || {};
  var channels = Object.keys(chSet)
    .filter(function (c) {
      if ((_chPrefs[c] || {}).is_hidden) return false;
      if ((globalThis as any)._topoHidden.channels[c]) return false;
      return true;
    })
    .sort();

  /* Size from the grid's inner box. Fall back to generous defaults on
   * first render when clientWidth is still 0. Leave room for labels so
   * long agent names don't get clipped at the viewport edge. */
  var W = Math.max(grid.clientWidth || 0, 600);
  var H = Math.max(grid.clientHeight || 0, 420);
  /* pad: reserved edge space for agent badges (they have long names
   * like head-mba@Yusukes-MacBook-Air.local). Pushed agents toward
   * the canvas edge; inner channel ring is more compact so the two
   * rings don't crowd each other. ywatanabe 2026-04-19: "agents
   * should be more outside as they sometimes overlaps channels". */
  var pad = 100;
  var cx = W / 2;
  var cy = H / 2;
  var rOuter = Math.max(80, Math.min(W, H) / 2 - pad);
  var rInner = Math.max(40, rOuter * 0.42);

  function _pt(r, i, n) {
    /* Start at -90° so the first node sits at 12 o'clock. */
    var theta = (i / Math.max(1, n)) * Math.PI * 2 - Math.PI / 2;
    return { x: cx + r * Math.cos(theta), y: cy + r * Math.sin(theta) };
  }

  /* Human user node — the signed-in human sits on the outer ring
   * alongside agents so their posts animate from a real origin node
   * (not just an in-place channel burst) and incoming replies animate
   * back to them. ywatanabe 2026-04-19: "me, user should be another
   * node". Slotted first so it sits at 12 o'clock and is easy to
   * locate. Key in agentPos is the literal username so the existing
   * _topoPulseEdge(sender,channel) path finds it without special-
   * casing the sender field. */
  var humanName =
    (typeof userName !== "undefined" && userName) ||
    window.__orochiUserName ||
    "";
  var nSlots = visible.length + (humanName ? 1 : 0);
  var agentPos = {};
  if (humanName) {
    agentPos[humanName] = _pt(rOuter, 0, nSlots);
  }
  visible.forEach(function (a, i) {
    agentPos[a.name] = _pt(rOuter, i + (humanName ? 1 : 0), nSlots);
  });
  var chPos = {};
  /* Phase-offset the inner ring by half a channel-slot (Δθ = π/N) so
   * radial user→channel lines land BETWEEN outer-ring agent positions
   * rather than passing through them. Without this, a human→channel
   * line looks like a 3-node chain (human → outer-agent → channel)
   * when the channel sits behind an agent at the same angle.
   * ywatanabe 2026-04-19 todo#95. */
  channels.forEach(function (c, i) {
    var n = Math.max(1, channels.length);
    var theta = ((i + 0.5) / n) * Math.PI * 2 - Math.PI / 2;
    chPos[c] = {
      x: cx + rInner * Math.cos(theta),
      y: cy + rInner * Math.sin(theta),
    };
  });
  /* Apply manual position overrides — user-dragged nodes on the canvas
   * pin at their drop coordinate, superseding the ring slot. Keys live
   * in _topoManualPositions and are keyed by "<kind>:<name>". */
  if (humanName) {
    var _mpH = _topoManualPositions[_topoManualKey("agent", humanName)];
    if (_mpH) agentPos[humanName] = { x: _mpH.x, y: _mpH.y };
  }
  visible.forEach(function (a) {
    var _mpA = _topoManualPositions[_topoManualKey("agent", a.name)];
    if (_mpA) agentPos[a.name] = { x: _mpA.x, y: _mpA.y };
  });
  channels.forEach(function (c) {
    var _mpC = _topoManualPositions[_topoManualKey("channel", c)];
    if (_mpC) chPos[c] = { x: _mpC.x, y: _mpC.y };
  });
  /* Stash for the message-pulse animator (_topoPulseEdge). Re-computed
   * on every render so a window-resize or agent add/remove still
   * targets the right coordinates. */
  (globalThis as any)._topoLastPositions = { agents: agentPos, channels: chPos };

  /* Kick off (or refresh) the per-channel permission fetch. Arrows
   * render immediately with the read-write default and upgrade in
   * place once each fetch resolves. */
  _refreshTopoPerms(channels);

  var edgesSvg = _topoBuildEdgesHtml(visible, agentPos, chPos, chSet, humanName);

  var chAgentCounts = {};
  visible.forEach(function (a) {
    (a.channels || []).forEach(function (c) {
      if (!chSet[c]) return;
      chAgentCounts[c] = (chAgentCounts[c] || 0) + 1;
    });
  });
  var _chPrefs = window._channelPrefs || {};
  var chSvg = _topoBuildChannelsSvg(visible, channels, chPos, chSet, _chPrefs);

  var agentSvg = _topoBuildAgentsSvg(visible, agentPos);

  var humanSvg = _topoBuildHumanSvg(humanName, agentPos);

  /* Auto-fit viewBox on first render: compute bbox over every node
   * (agents + human + channel diamonds) with rough badge-width
   * estimates so long-name agents on the right/bottom aren't
   * clipped. Persisted zoom/pan overrides this once user has
   * interacted. ywatanabe 2026-04-19: "by default the size of the
   * graph must be maximized to include all elements". */
  var vb;
  if ((globalThis as any)._topoViewBox) {
    vb = (globalThis as any)._topoViewBox;
  } else {
    var bMinX = Infinity,
      bMinY = Infinity,
      bMaxX = -Infinity,
      bMaxY = -Infinity;
    visible.forEach(function (a) {
      var p = agentPos[a.name];
      if (!p) return;
      var nm = a.name || "";
      var w = Math.max(40, nm.length * 6.5) + 60; /* badge + glyph + LEDs */
      bMinX = Math.min(bMinX, p.x - 34);
      bMaxX = Math.max(bMaxX, p.x + w);
      bMinY = Math.min(bMinY, p.y - 14);
      bMaxY = Math.max(bMaxY, p.y + 14);
    });
    if (humanName && agentPos[humanName]) {
      var hp2 = agentPos[humanName];
      var hw = Math.max(40, humanName.length * 6.5) + 40;
      bMinX = Math.min(bMinX, hp2.x - 20);
      bMaxX = Math.max(bMaxX, hp2.x + hw);
      bMinY = Math.min(bMinY, hp2.y - 14);
      bMaxY = Math.max(bMaxY, hp2.y + 14);
    }
    channels.forEach(function (c) {
      var p = chPos[c];
      if (!p) return;
      var r = 22; /* max diamond radius */
      bMinX = Math.min(bMinX, p.x - r - (c.length * 6.5) / 2);
      bMaxX = Math.max(bMaxX, p.x + r + (c.length * 6.5) / 2);
      bMinY = Math.min(bMinY, p.y - r - 16);
      bMaxY = Math.max(bMaxY, p.y + r + 6);
    });
    if (isFinite(bMinX)) {
      /* Clamp viewBox to at least the SVG's rendered dimensions so a
       * tight bbox (small ring layout) never magnifies nodes past 1x.
       * Center the content within the clamped frame so padding is
       * distributed evenly. ywatanabe 2026-04-19: initial render was
       * ~4x-zoomed because bbox (~400x300) was much smaller than the
       * SVG canvas (~1500x900). */
      var pad2 = 24;
      var vbW = Math.max(bMaxX - bMinX + pad2 * 2, W);
      var vbH = Math.max(bMaxY - bMinY + pad2 * 2, H);
      var cx = (bMinX + bMaxX) / 2;
      var cy = (bMinY + bMaxY) / 2;
      vb = { x: cx - vbW / 2, y: cy - vbH / 2, w: vbW, h: vbH };
    } else {
      vb = { x: 0, y: 0, w: W, h: H };
    }
  }
  /* <defs> carries two permission-direction markers. refX is placed
   * so the arrow tip sits just off the line end — otherwise it would
   * overlap the LED/diamond node. markerUnits=userSpaceOnUse so the
   * triangle scales with viewBox zoom (vanishes gracefully when the
   * user zooms out to survey the whole graph). */
  var markerDefs =
    "<defs>" +
    '<marker id="topo-arrow-end" viewBox="0 0 10 10" refX="9" refY="5"' +
    ' markerWidth="6" markerHeight="6" orient="auto-start-reverse"' +
    ' markerUnits="userSpaceOnUse">' +
    '<path d="M0,0 L10,5 L0,10 z" fill="#4ecdc4" class="topo-arrow-head"/>' +
    "</marker>" +
    '<marker id="topo-arrow-start" viewBox="0 0 10 10" refX="9" refY="5"' +
    ' markerWidth="6" markerHeight="6" orient="auto-start-reverse"' +
    ' markerUnits="userSpaceOnUse">' +
    '<path d="M0,0 L10,5 L0,10 z" fill="#4ecdc4" class="topo-arrow-head"/>' +
    "</marker>" +
    "</defs>";
  var svg =
    '<svg class="topo-svg" width="' +
    W +
    '" height="' +
    H +
    '" viewBox="' +
    vb.x.toFixed(1) +
    " " +
    vb.y.toFixed(1) +
    " " +
    vb.w.toFixed(1) +
    " " +
    vb.h.toFixed(1) +
    '" xmlns="http://www.w3.org/2000/svg">' +
    markerDefs +
    '<g class="topo-edges">' +
    edgesSvg +
    "</g>" +
    '<g class="topo-channels">' +
    chSvg +
    "</g>" +
    '<g class="topo-agents">' +
    agentSvg +
    humanSvg +
    "</g>" +
    '<rect class="topo-zoombox" x="0" y="0" width="0" height="0"' +
    ' fill="rgba(78,205,196,0.1)" stroke="#4ecdc4" stroke-width="1"' +
    ' stroke-dasharray="4 4" style="display:none;pointer-events:none"/>' +
    '<rect class="topo-lasso" x="0" y="0" width="0" height="0"' +
    ' fill="rgba(251,191,36,0.12)" stroke="#fbbf24" stroke-width="1"' +
    ' stroke-dasharray="3 3" style="display:none;pointer-events:none"/>' +
    "</svg>";

  var detailBox = "";
  if ((globalThis as any)._overviewExpanded) {
    detailBox =
      '<div class="activity-inline-detail" data-detail-for="' +
      escapeHtml((globalThis as any)._overviewExpanded) +
      '"><p class="empty-notice">Loading detail…</p></div>';
  }
  var hint =
    '<div class="topo-hint">drag = rectangle zoom · shift+drag = pan · ctrl+drag = lasso · shift+click agent = multi-select · wheel = zoom · esc = back · 0 = reset · dbl-click channel = post</div>';
  /* Floating action bar — visible only when ≥2 agents are selected.
   * Markup always rendered so the same event-delegation wiring works;
   * visibility toggled via a CSS class. */
  var selNames = _topoSelectedNames();
  var barCls =
    "topo-actionbar" + (selNames.length >= 2 ? " topo-actionbar-show" : "");
  var actionBar =
    '<div class="' +
    barCls +
    '" role="toolbar">' +
    '<span class="topo-actionbar-count">' +
    selNames.length +
    " selected</span>" +
    '<button type="button" class="topo-actionbar-btn" data-topo-action="post">post to selected agents</button>' +
    '<button type="button" class="topo-actionbar-btn topo-actionbar-btn-ghost" data-topo-action="clear">clear</button>' +
    "</div>";
  var ctrls =
    '<div class="topo-ctrls">' +
    '<button type="button" class="topo-ctrl-btn" data-topo-ctrl="back" title="Previous zoom (Escape)">↶</button>' +
    '<button type="button" class="topo-ctrl-btn" data-topo-ctrl="forward" title="Next zoom (redo)">↷</button>' +
    '<button type="button" class="topo-ctrl-btn" data-topo-ctrl="minus" title="Zoom out (−)">−</button>' +
    '<button type="button" class="topo-ctrl-btn" data-topo-ctrl="reset" title="Reset zoom (0)">0</button>' +
    '<button type="button" class="topo-ctrl-btn" data-topo-ctrl="plus" title="Zoom in (+)">+</button>' +
    /* todo#305: 整列 (Tidy) button — runs concentric-ring auto-layout
     * (inner = channels, outer = agents + human) with two light
     * repulsion passes so overlapping nodes spread out. Layout only
     * runs on explicit click; drag / zoom / pan are unchanged. */
    '<button type="button" class="topo-ctrl-btn topology-autolayout-btn" data-topo-ctrl="integrate" title="整列 (auto-layout: channels inner, agents outer)">整列</button>' +
    "</div>";
  var pool = _topoBuildPoolHtml(visible, channels);
  /* todo#67 — Time seekbar + play button docked at the bottom of the
   * topology canvas. Shows the last TOPO_SEEK_WINDOW_MS of pulse events;
   * drag the slider to enter playback mode, press ▶ to replay forward
   * from the playhead. All event listeners are attached via delegation
   * in _wireTopoSeekbar so they survive heartbeat-driven re-renders. */
  var seekBar = _topoSeekbarHtml();
  grid.innerHTML =
    '<div class="topo-wrap">' +
    hint +
    ctrls +
    pool +
    svg +
    actionBar +
    seekBar +
    "</div>" +
    detailBox;

  /* Delegated click: agent node → toggle expand. Bound ONCE on the
   * grid (the delegation helper guards with _overviewGridWired). We
   * extend its reach here because the grid rewrites its innerHTML on
   * every heartbeat and per-element listeners would be lost. */
  _wireOverviewGridDelegation(grid);
  _wireTopoZoomPan(grid, W, H);
  _wireTopoSeekbar(grid);
  _topoSeekUpdateUI();
  /* todo#97 — Force a heatmap paint after layout settles. The initial
   * _topoSeekUpdateUI may run before the canvas gets its flexed width,
   * so schedule one more forced paint on rAF when dimensions are real. */
  requestAnimationFrame(function () {
    _topoSeekHeatRefresh(true);
  });
  /* todo#79: after a fresh topology render, re-apply the pool-as-filter
   * dim classes so the persisted selection survives heartbeat re-renders
   * (without this, every 2s heartbeat would flash the full graph back
   * in before the user's filter is re-applied). */
  _topoPoolSelectionPaint(grid);

  if ((globalThis as any)._overviewExpanded) {
    var agent = (window.__lastAgents || []).find(function (x) {
      return x.name === (globalThis as any)._overviewExpanded;
    });
    var inlineBox = grid.querySelector(
      '.activity-inline-detail[data-detail-for="' +
        String((globalThis as any)._overviewExpanded).replace(/"/g, '\\"') +
        '"]',
    );
    if (agent && inlineBox) {
      _renderActivityAgentDetail(agent, inlineBox);
      _fetchActivityDetail(agent.name);
    }
  }
}

