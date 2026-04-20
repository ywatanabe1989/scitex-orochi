// @ts-nocheck
// Migrated classic-script file. Types intentionally loose during
// the big-bang JS-to-TS bundle migration. Narrow later, per-file.
/* activity-tab/topology-edges.js — edge-list computation (fan-out
 * pre-pass) + <line> SVG emission for the topology canvas. */


function _topoBuildEdgesHtml(visible, agentPos, chPos, chSet, humanName) {
  /* Edges — iterate visible agents, intersect with the channel set.
   * Each <line> carries data-channel/data-agent so _repaintTopoArrows()
   * can re-apply marker-start/marker-end without touching geometry.
   *
   * We emit a PAIR per edge: an invisible 12px-wide .topo-edge-hit
   * overlay (fires click/hover events) followed by the visible .topo-edge
   * (decorative only — pointer-events:none). The hit overlay carries the
   * data-* attributes because event delegation keys off it; the visible
   * line is brightened via the CSS adjacent-sibling selector
   * `.topo-edge-hit:hover + .topo-edge`. Emitting the hit overlay FIRST
   * ensures the sibling combinator lights up the correct visible line.
   * ywatanabe 2026-04-19: "hitarea of edges should be a bit broader" —
   * the earlier stroke-width 1→2 bump was insufficient.
   *
   * Fan-out pre-pass (todo#77): when two edges leave the same source at
   * nearly the same angle, the resulting straight lines visually merge
   * into one "ywatanabe -> #agent -> #proj-ripple-wm" that falsely
   * suggests a 3-node chain. We detect clusters of near-collinear
   * outgoing edges (<12° apart) and displace each start point by a few
   * px perpendicular to its own direction, so the cluster fans out from
   * the source node's perimeter instead of sharing one point. The hit
   * overlay and visible line share the same offset so hover/click stay
   * aligned. Target points are untouched; the packet animator in
   * _topoPulseEdge reads _topoLastPositions (source/target centers) and
   * still animates along the visual midline — perfectly acceptable
   * because the offset is <=7px. */
  var FAN_ANGLE_THRESHOLD = 12 * (Math.PI / 180); /* radians */
  var FAN_STEP_PX = 3.5; /* perpendicular displacement per cluster step */

  /* Collect every outgoing edge (agent→channel + human→channel) keyed by
   * source so we can compute cluster-aware offsets before emission. */
  var _edgeList = []; /* {sourceKey, sx, sy, tx, ty, angle, kind, a, c} */
  visible.forEach(function (a) {
    var ap = agentPos[a.name];
    if (!ap) return;
    (a.channels || []).forEach(function (c) {
      var cp = chPos[c];
      if (!cp) return;
      _edgeList.push({
        sourceKey: "a:" + a.name,
        sx: ap.x,
        sy: ap.y,
        tx: cp.x,
        ty: cp.y,
        angle: Math.atan2(cp.y - ap.y, cp.x - ap.x),
        kind: "agent",
        a: a.name,
        c: c,
      });
    });
  });
  var _humanPrefsMap = null;
  if (humanName && agentPos[humanName]) {
    var _hp = agentPos[humanName];
    _humanPrefsMap =
      (typeof window !== "undefined" && window._channelPrefs) ||
      (typeof _channelPrefs !== "undefined" ? _channelPrefs : {}) ||
      {};
    Object.keys(_humanPrefsMap).forEach(function (c) {
      if (!c || c.indexOf("dm:") === 0) return;
      var pref = _humanPrefsMap[c] || {};
      if (pref.is_hidden) return;
      if (!chSet[c]) return;
      var cp = chPos[c];
      if (!cp) return;
      _edgeList.push({
        sourceKey: "h:" + humanName,
        sx: _hp.x,
        sy: _hp.y,
        tx: cp.x,
        ty: cp.y,
        angle: Math.atan2(cp.y - _hp.y, cp.x - _hp.x),
        kind: "human",
        a: humanName,
        c: c,
      });
    });
  }
  /* Bucket by source, sort within bucket by angle, tag each edge with a
   * perpendicular offset that fans out near-collinear neighbours. */
  var _bySource = {};
  _edgeList.forEach(function (e) {
    (_bySource[e.sourceKey] = _bySource[e.sourceKey] || []).push(e);
  });
  Object.keys(_bySource).forEach(function (src) {
    var arr = _bySource[src];
    if (arr.length < 2) {
      arr[0].ox = 0;
      arr[0].oy = 0;
      return;
    }
    arr.sort(function (p, q) {
      return p.angle - q.angle;
    });
    /* Walk sorted edges; whenever the next edge is within the threshold
     * of the previous, they share a cluster. Members of a cluster of
     * size N are displaced by (i - (N-1)/2) * FAN_STEP_PX perpendicular
     * to their own direction, so the cluster fans symmetrically. */
    var i = 0;
    while (i < arr.length) {
      var j = i + 1;
      while (
        j < arr.length &&
        Math.abs(arr[j].angle - arr[j - 1].angle) < FAN_ANGLE_THRESHOLD
      ) {
        j++;
      }
      var clusterSize = j - i;
      for (var k = i; k < j; k++) {
        var e = arr[k];
        if (clusterSize === 1) {
          e.ox = 0;
          e.oy = 0;
        } else {
          var rank = k - i - (clusterSize - 1) / 2;
          /* Perpendicular unit vector to (tx-sx, ty-sy), then scale. */
          var dx = e.tx - e.sx;
          var dy = e.ty - e.sy;
          var len = Math.sqrt(dx * dx + dy * dy) || 1;
          var px = -dy / len;
          var py = dx / len;
          e.ox = px * rank * FAN_STEP_PX;
          e.oy = py * rank * FAN_STEP_PX;
        }
      }
      i = j;
    }
  });
  /* Re-key for O(1) lookup by (source, channel) when emitting. */
  var _fanOffset = {};
  _edgeList.forEach(function (e) {
    _fanOffset[e.sourceKey + "|" + e.c] = { ox: e.ox || 0, oy: e.oy || 0 };
  });

  var edgesSvg = "";
  visible.forEach(function (a) {
    var ap = agentPos[a.name];
    (a.channels || []).forEach(function (c) {
      var cp = chPos[c];
      if (!ap || !cp) return;
      var perm = _topoChannelPerms[_permKey(c, a.name)] || "read-write";
      var markers = _markerAttrsForPerm(perm);
      var off = _fanOffset["a:" + a.name + "|" + c] || { ox: 0, oy: 0 };
      var coords =
        ' x1="' +
        (ap.x + off.ox).toFixed(1) +
        '" y1="' +
        (ap.y + off.oy).toFixed(1) +
        '" x2="' +
        cp.x.toFixed(1) +
        '" y2="' +
        cp.y.toFixed(1) +
        '"';
      edgesSvg +=
        '<line class="topo-edge-hit" data-agent="' +
        escapeHtml(a.name) +
        '" data-channel="' +
        escapeHtml(c) +
        '"' +
        coords +
        "/>";
      edgesSvg +=
        '<line class="topo-edge" data-agent="' +
        escapeHtml(a.name) +
        '" data-channel="' +
        escapeHtml(c) +
        '"' +
        coords +
        ' stroke="#2a3a40" stroke-opacity="0.6" stroke-width="1"' +
        markers +
        "/>";
    });
  });

  /* Human → subscribed-channel edges. We only draw a dashed line from
   * the human node to channels the signed-in user is actually
   * subscribed to (sidebar signal: _channelPrefs keys that are NOT
   * DM pseudo-channels and NOT hidden). Intentionally excludes
   * agents — humans and agents must not appear directly connected
   * (ywatanabe 2026-04-19). Previous fan-out to *every* channel was
   * removed in b313ae7; this restores only the subscribed subset. */
  if (humanName && agentPos[humanName]) {
    var hp = agentPos[humanName];
    var prefsMap =
      _humanPrefsMap ||
      (typeof window !== "undefined" && window._channelPrefs) ||
      (typeof _channelPrefs !== "undefined" ? _channelPrefs : {}) ||
      {};
    Object.keys(prefsMap).forEach(function (c) {
      if (!c || c.indexOf("dm:") === 0) return;
      var pref = prefsMap[c] || {};
      if (pref.is_hidden) return;
      if (!chSet[c]) return; /* channel not on current canvas */
      var cp = chPos[c];
      if (!cp) return;
      var hOff = _fanOffset["h:" + humanName + "|" + c] || { ox: 0, oy: 0 };
      var hCoords =
        ' x1="' +
        (hp.x + hOff.ox).toFixed(1) +
        '" y1="' +
        (hp.y + hOff.oy).toFixed(1) +
        '" x2="' +
        cp.x.toFixed(1) +
        '" y2="' +
        cp.y.toFixed(1) +
        '"';
      /* Hit overlay first (wide invisible target) + visible dashed edge.
       * Same pairing rationale as the agent→channel case above. */
      edgesSvg +=
        '<line class="topo-edge-hit topo-edge-hit-human" data-agent="' +
        escapeHtml(humanName) +
        '" data-channel="' +
        escapeHtml(c) +
        '"' +
        hCoords +
        "/>";
      edgesSvg +=
        '<line class="topo-edge topo-edge-human" data-agent="' +
        escapeHtml(humanName) +
        '" data-channel="' +
        escapeHtml(c) +
        '"' +
        hCoords +
        ' stroke="#fbbf24" stroke-opacity="0.25" stroke-width="1"' +
        ' stroke-dasharray="3 4"/>';
    });
  }

  /* DM edges intentionally NOT drawn on the canvas — per ywatanabe
   * 2026-04-19 "humans and agents must not be connected on topology".
   * Human↔subscribed-channel dashed lines are drawn above; all DM edges
   * (human↔agent, agent↔agent) are gone from the canvas. The DM packet
   * animation still fires via _topoPulseEdge using _topoLastPositions,
   * so messages visibly flow from sender to recipient without a
   * pre-drawn edge. */

  return edgesSvg;
}
