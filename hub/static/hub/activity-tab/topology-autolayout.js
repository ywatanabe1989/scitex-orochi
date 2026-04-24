/* activity-tab/topology-autolayout.js — "整列" (Tidy) button handler.
 *
 * Re-lays out the topology graph into two concentric rings:
 *   - Inner ring  = channel nodes
 *   - Outer ring  = agents + human user
 *
 * Then runs a couple of light repulsion passes so no two nodes sit
 * within ~1.2 * node_diameter of each other. Positions are written into
 * _topoManualPositions (the same overlay drag-to-reposition uses) so
 * layout survives heartbeat re-renders and zoom/pan.
 *
 * Mirrors hub/frontend/src/activity-tab/topology-autolayout.ts. Legacy
 * classic-script file kept in lockstep with the TS source per the PR
 * #285/#293 pattern, even though only the vite bundle is served today.
 */

var _TOPO_AUTOLAYOUT_NODE_D = 48;
var _TOPO_AUTOLAYOUT_MIN_SEP = _TOPO_AUTOLAYOUT_NODE_D * 1.2;

function _topoAutoLayoutRepulsePass(nodes, anchors, strength) {
  var i, j, a, b, dx, dy, d, overlap, ux, uy;
  for (i = 0; i < nodes.length; i++) {
    for (j = i + 1; j < nodes.length; j++) {
      a = nodes[i];
      b = nodes[j];
      dx = b.x - a.x;
      dy = b.y - a.y;
      d = Math.sqrt(dx * dx + dy * dy);
      if (d >= _TOPO_AUTOLAYOUT_MIN_SEP) continue;
      if (d < 0.01) {
        ux = 1;
        uy = 0;
        d = 0.01;
      } else {
        ux = dx / d;
        uy = dy / d;
      }
      overlap = (_TOPO_AUTOLAYOUT_MIN_SEP - d) * 0.5 * strength;
      a.x -= ux * overlap;
      a.y -= uy * overlap;
      b.x += ux * overlap;
      b.y += uy * overlap;
    }
  }
  for (i = 0; i < nodes.length; i++) {
    var anc = anchors[nodes[i].key];
    if (!anc) continue;
    nodes[i].x += (anc.x - nodes[i].x) * 0.05;
    nodes[i].y += (anc.y - nodes[i].y) * 0.05;
  }
}

function _topoAutoLayout() {
  var agents = window.__lastAgents || [];
  var hidden = _topoHidden || { agents: {}, channels: {} };
  var chPrefs = window._channelPrefs || {};
  var hn =
    (typeof userName !== "undefined" && userName) ||
    window.__orochiUserName ||
    "";

  var visible = agents.filter(function (a) {
    if (hidden.agents && hidden.agents[a.name]) return false;
    if (a.status === "offline" && !a.pinned) return false;
    return true;
  });

  var chSet = {};
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

  var grid = document.querySelector(".activity-view-topology .topo-wrap");
  var W = Math.max((grid && grid.clientWidth) || 0, 600);
  var H = Math.max((grid && grid.clientHeight) || 0, 420);
  var cx = W / 2;
  var cy = H / 2;
  var pad = 100;
  var rOuter = Math.max(80, Math.min(W, H) / 2 - pad);
  var rInner = Math.max(40, rOuter * 0.42);

  var nodes = [];
  var anchors = {};

  channels.forEach(function (c, i) {
    var n = Math.max(1, channels.length);
    var theta = ((i + 0.5) / n) * Math.PI * 2 - Math.PI / 2;
    var p = {
      x: cx + rInner * Math.cos(theta),
      y: cy + rInner * Math.sin(theta),
    };
    var key = _topoManualKey("channel", c);
    anchors[key] = p;
    nodes.push({ key: key, kind: "channel", name: c, x: p.x, y: p.y });
  });

  var nOuter = visible.length + (hn ? 1 : 0);
  var outerIdx = 0;
  if (hn) {
    var thetaH = (outerIdx / Math.max(1, nOuter)) * Math.PI * 2 - Math.PI / 2;
    var pH = {
      x: cx + rOuter * Math.cos(thetaH),
      y: cy + rOuter * Math.sin(thetaH),
    };
    var keyH = _topoManualKey("agent", hn);
    anchors[keyH] = pH;
    nodes.push({ key: keyH, kind: "agent", name: hn, x: pH.x, y: pH.y });
    outerIdx++;
  }
  visible.forEach(function (a) {
    var thetaA = (outerIdx / Math.max(1, nOuter)) * Math.PI * 2 - Math.PI / 2;
    var pA = {
      x: cx + rOuter * Math.cos(thetaA),
      y: cy + rOuter * Math.sin(thetaA),
    };
    var keyA = _topoManualKey("agent", a.name);
    anchors[keyA] = pA;
    nodes.push({ key: keyA, kind: "agent", name: a.name, x: pA.x, y: pA.y });
    outerIdx++;
  });

  _topoAutoLayoutRepulsePass(nodes, anchors, 1.0);
  _topoAutoLayoutRepulsePass(nodes, anchors, 0.7);

  nodes.forEach(function (n) {
    _topoManualPositions[n.key] = { x: n.x, y: n.y };
  });
  _topoSaveManualPositions();

  _topoLastSig = "";
}
