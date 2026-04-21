// @ts-nocheck
import {
  _topoClearManualPosition,
  _topoManualKey,
  _topoManualPositions,
  _topoSaveManualPositions,
} from "./state";
import { userName } from "../app/utils";

/* activity-tab/topology-autolayout.ts — "Reset Layout" button handler.
 *
 * Re-lays out the topology graph into two concentric rings:
 *   - Inner ring  = channel nodes
 *   - Outer ring  = agents + human user
 *
 * Then runs a force-directed relaxation loop so no two nodes sit within
 * ~1.1 * node_diameter of each other. Positions are written into
 * _topoManualPositions (the same overlay that drag-to-reposition uses)
 * so the layout survives heartbeat re-renders and zoom/pan.
 *
 * No deps; pure math. ywatanabe 2026-04-20 lead msg#15493 / todo#305 +
 * PR #<this> Item 8 (zero-overlap guarantee).
 */

/* Approximate node footprint used for the overlap-relief pass. The
 * topology renderer uses badge-pill nodes ≈ 90px wide × 22px tall for
 * agents and ≈ 60px wide × 22px tall for channels (post-PR#310 — no
 * more diamonds). We use a circumscribed diameter of 90 for the
 * repulsion radius so wide pills don't visually overlap even when
 * their centres are exactly `_NODE_D * 1.1` apart.
 *
 * Item 8 "guarantee: for N < (some threshold) nodes with the canvas
 * dimensions available, post-layout every pair is at least
 * node_diameter × 1.1 apart". */
var _NODE_D = 90;
var _MIN_SEP = _NODE_D * 1.1; /* ~99px */
var _MAX_ITER = 300;

/* One repulsion pass — O(n²) over the node set, fine for <200 nodes.
 * For each close pair, push them apart along the connecting vector by
 * half the overlap each. `anchors` holds the target-ring position so a
 * displaced node is also softly pulled back toward its assigned ring
 * slot; without this a dense cluster can spiral outward forever.
 *
 * Returns the number of overlapping pairs observed in this pass so the
 * caller's relaxation loop can terminate early when no overlap remains
 * (PR #<this> Item 8). */
function _repulsePass(nodes, anchors, strength) {
  var i, j, a, b, dx, dy, d, overlap, ux, uy;
  var overlapCount = 0;
  for (i = 0; i < nodes.length; i++) {
    for (j = i + 1; j < nodes.length; j++) {
      a = nodes[i];
      b = nodes[j];
      dx = b.x - a.x;
      dy = b.y - a.y;
      d = Math.sqrt(dx * dx + dy * dy);
      if (d >= _MIN_SEP) continue;
      overlapCount++;
      if (d < 0.01) {
        /* Co-located — nudge along a deterministic axis. Use node
         * index parity so repeat-overlapping pairs drift apart
         * consistently across iterations. */
        ux = (i + j) % 2 === 0 ? 1 : -1;
        uy = 0;
        d = 0.01;
      } else {
        ux = dx / d;
        uy = dy / d;
      }
      overlap = (_MIN_SEP - d) * 0.5 * strength;
      a.x -= ux * overlap;
      a.y -= uy * overlap;
      b.x += ux * overlap;
      b.y += uy * overlap;
    }
  }
  /* Anchor attraction — pull every node ~5% back toward its ring slot
   * so the two rings stay recognisable after the nudges above. */
  for (i = 0; i < nodes.length; i++) {
    var anc = anchors[nodes[i].key];
    if (!anc) continue;
    nodes[i].x += (anc.x - nodes[i].x) * 0.05;
    nodes[i].y += (anc.y - nodes[i].y) * 0.05;
  }
  return overlapCount;
}

/* Compute concentric ring positions for the currently-visible topology
 * and write them into _topoManualPositions. Called from the "整列"
 * button in the topology ctrls toolbar. */
export function _topoAutoLayout() {
  /* Data sources: the last render stashed positions + the visible agent
   * list on window.__lastAgents. We re-derive channels from those
   * agents the same way topology.ts does. */
  var agents = (window as any).__lastAgents || [];
  var hidden = (globalThis as any)._topoHidden || { agents: {}, channels: {} };
  var chPrefs = (window as any)._channelPrefs || {};
  var hn =
    (typeof userName !== "undefined" && userName) ||
    (window as any).__orochiUserName ||
    "";

  /* Filter visible agents — same rules as _renderActivityTopology. */
  var visible = agents.filter(function (a) {
    if (hidden.agents && hidden.agents[a.name]) return false;
    /* Dead/unpinned rows: _isDeadAgent lives in utils, but we can't
     * cheaply import it here without cycles. Approximate by treating
     * rows with status === "offline" and !pinned as dead — the 整列
     * button is a visual aid; a missed row self-corrects on next
     * full render. */
    if (a.status === "offline" && !a.pinned) return false;
    return true;
  });

  /* Collect channels referenced by at least one visible agent + every
   * workspace channel from channelPrefs (zero-subscriber channels must
   * still lay out as connectable nodes — same contract as the renderer). */
  var chSet: Record<string, boolean> = {};
  visible.forEach(function (a) {
    (a.channels || []).forEach(function (c) {
      if (!c || c.indexOf("dm:") === 0) return;
      chSet[c] = true;
    });
  });
  Object.keys(chPrefs).forEach(function (c) {
    if (!c || c.indexOf("dm:") === 0) return;
    chSet[c] = true;
  });
  var channels = Object.keys(chSet)
    .filter(function (c) {
      if ((chPrefs[c] || {}).is_hidden) return false;
      if (hidden.channels && hidden.channels[c]) return false;
      return true;
    })
    .sort();

  /* Canvas size — match the renderer's fallbacks. */
  var grid = document.querySelector(
    ".activity-view-topology .topo-wrap",
  ) as HTMLElement | null;
  var W = Math.max((grid && grid.clientWidth) || 0, 600);
  var H = Math.max((grid && grid.clientHeight) || 0, 420);
  var cx = W / 2;
  var cy = H / 2;
  var pad = 100;
  var rOuter = Math.max(80, Math.min(W, H) / 2 - pad);
  var rInner = Math.max(40, rOuter * 0.42);

  /* Assign ring slots — channels on inner ring, agents+human on outer. */
  var nodes: Array<{ key: string; kind: string; name: string; x: number; y: number }> = [];
  var anchors: Record<string, { x: number; y: number }> = {};

  channels.forEach(function (c, i) {
    var n = Math.max(1, channels.length);
    var theta = ((i + 0.5) / n) * Math.PI * 2 - Math.PI / 2;
    var p = { x: cx + rInner * Math.cos(theta), y: cy + rInner * Math.sin(theta) };
    var key = _topoManualKey("channel", c);
    anchors[key] = p;
    nodes.push({ key: key, kind: "channel", name: c, x: p.x, y: p.y });
  });

  var nOuter = visible.length + (hn ? 1 : 0);
  var outerIdx = 0;
  if (hn) {
    var thetaH = (outerIdx / Math.max(1, nOuter)) * Math.PI * 2 - Math.PI / 2;
    var pH = { x: cx + rOuter * Math.cos(thetaH), y: cy + rOuter * Math.sin(thetaH) };
    var keyH = _topoManualKey("agent", hn);
    anchors[keyH] = pH;
    nodes.push({ key: keyH, kind: "agent", name: hn, x: pH.x, y: pH.y });
    outerIdx++;
  }
  visible.forEach(function (a) {
    var thetaA = (outerIdx / Math.max(1, nOuter)) * Math.PI * 2 - Math.PI / 2;
    var pA = { x: cx + rOuter * Math.cos(thetaA), y: cy + rOuter * Math.sin(thetaA) };
    var keyA = _topoManualKey("agent", a.name);
    anchors[keyA] = pA;
    nodes.push({ key: keyA, kind: "agent", name: a.name, x: pA.x, y: pA.y });
    outerIdx++;
  });

  /* PR #<this> Item 8: force-directed relaxation loop with zero-overlap
   * guarantee. Run up to _MAX_ITER passes; exit early when no pair
   * overlaps. Strength decays over iterations so early passes move
   * fast and late passes fine-tune without oscillation. Each iteration
   * is O(n²); at N < 200 nodes and 300 iter cap this is <60k op/pass
   * which runs instantly in the browser.
   *
   * If the canvas literally cannot fit the nodes (rOuter × 2π < N ×
   * _MIN_SEP), we still relax to the best-effort spacing but log a
   * console warning so the user knows the layout is saturated. */
  var idealOuterSpacing =
    (2 * Math.PI * rOuter) / Math.max(1, nOuter);
  var idealInnerSpacing =
    (2 * Math.PI * rInner) / Math.max(1, channels.length);
  var saturated =
    idealOuterSpacing < _MIN_SEP || idealInnerSpacing < _MIN_SEP;
  if (saturated) {
    console.warn(
      "[topology-autolayout] canvas saturated: best-effort spacing " +
        "(" +
        Math.round(Math.min(idealOuterSpacing, idealInnerSpacing)) +
        "px < " +
        Math.round(_MIN_SEP) +
        "px target). Consider hiding some agents/channels or " +
        "enlarging the viewport.",
    );
  }
  var iter;
  var overlap = 0;
  for (iter = 0; iter < _MAX_ITER; iter++) {
    /* Strength decays linearly from 1.0 → 0.3 over the iteration cap
     * so early passes do bulk separation and late passes polish. */
    var strength = 1.0 - (iter / _MAX_ITER) * 0.7;
    overlap = _repulsePass(nodes, anchors, strength);
    /* Early-exit: no overlaps remaining = layout is clean. */
    if (overlap === 0) break;
  }
  if (overlap > 0 && !saturated) {
    /* Ran to the iteration cap without converging despite the canvas
     * having enough room — surface that so future tuning can raise
     * the cap if needed. */
    console.warn(
      "[topology-autolayout] did not converge after " +
        _MAX_ITER +
        " iterations, " +
        overlap +
        " overlapping pair(s) remain.",
    );
  }

  /* Write back into the manual-position overlay. We REPLACE every
   * existing entry for the keys we touched so partial drags don't
   * linger after the user asked for a tidy. Keys we didn't touch
   * (stale entries from agents no longer in the visible set) are
   * left alone — they'll age out when those entities reappear or
   * are reset manually. */
  nodes.forEach(function (n) {
    _topoManualPositions[n.key] = { x: n.x, y: n.y };
  });
  _topoSaveManualPositions();

  /* Invalidate the signature cache so the next render actually repaints
   * (the renderer short-circuits when its structural signature matches). */
  (globalThis as any)._topoLastSig = "";
}

/* Reset to pure ring layout by clearing all manual overrides — useful
 * as a companion affordance; not currently wired but exported for
 * future "reset layout" button reuse. */
export function _topoClearLayout() {
  Object.keys(_topoManualPositions).forEach(function (k) {
    delete _topoManualPositions[k];
  });
  _topoSaveManualPositions();
  (globalThis as any)._topoLastSig = "";
}
