/* Connectivity map — SSH mesh visualization in Machines tab */
/* globals: apiUrl, escapeHtml */

var connectivityCache = null;

async function fetchConnectivity() {
  try {
    var res = await fetch(apiUrl("/api/connectivity/"), { credentials: "same-origin" });
    if (!res.ok) return;
    connectivityCache = await res.json();
    renderConnectivityMap();
  } catch (e) {
    console.warn("fetchConnectivity error:", e);
  }
}

/* Layout: nodes evenly spaced around a circle */
function _layoutNodes(nodes, cx, cy, radius) {
  var positions = {};
  var n = nodes.length;
  if (n === 0) return positions;
  /* Special-case 1 node: center */
  if (n === 1) {
    positions[nodes[0].id] = { x: cx, y: cy };
    return positions;
  }
  /* Otherwise: evenly distribute around the circle, starting at top */
  for (var i = 0; i < n; i++) {
    var theta = -Math.PI / 2 + (2 * Math.PI * i) / n;
    positions[nodes[i].id] = {
      x: cx + radius * Math.cos(theta),
      y: cy + radius * Math.sin(theta),
    };
  }
  return positions;
}

/* Slightly offset two opposing edges so they don't overlap */
function _edgePath(p1, p2, offsetSign) {
  var dx = p2.x - p1.x;
  var dy = p2.y - p1.y;
  var len = Math.sqrt(dx * dx + dy * dy);
  if (len === 0) return "M " + p1.x + " " + p1.y + " L " + p2.x + " " + p2.y;
  /* Perpendicular offset for the "outbound" arc */
  var nx = -dy / len;
  var ny = dx / len;
  var off = 6 * (offsetSign || 0);
  var midx = (p1.x + p2.x) / 2 + nx * off * 4;
  var midy = (p1.y + p2.y) / 2 + ny * off * 4;
  /* Quadratic bezier so the arrow direction is visually distinct */
  return "M " + (p1.x + nx * off) + " " + (p1.y + ny * off) +
         " Q " + midx + " " + midy +
         " " + (p2.x + nx * off) + " " + (p2.y + ny * off);
}

function renderConnectivityMap() {
  var container = document.getElementById("connectivity-map");
  if (!container) return;
  if (!connectivityCache || !connectivityCache.nodes || connectivityCache.nodes.length === 0) {
    container.innerHTML = '<p class="empty-notice">No connectivity data.</p>';
    return;
  }
  var nodes = connectivityCache.nodes;
  var edges = connectivityCache.edges || [];
  var W = 480;
  var H = 360;
  var cx = W / 2;
  var cy = H / 2;
  var radius = 130;
  var nodeR = 28;
  var positions = _layoutNodes(nodes, cx, cy, radius);

  /* Pair up bidirectional edges so we can offset them */
  var edgeKey = function (e) { return e.source + "→" + e.target; };
  var seen = {};

  var svgParts = [];
  svgParts.push(
    '<svg class="connectivity-svg" viewBox="0 0 ' + W + ' ' + H + '" width="100%" height="' + H + '">'
  );
  /* Definitions: arrowhead markers in two colors */
  svgParts.push(
    '<defs>' +
    '<marker id="arrow-ok" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">' +
    '<path d="M 0 0 L 10 5 L 0 10 z" fill="#4ecdc4"/></marker>' +
    '<marker id="arrow-fail" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">' +
    '<path d="M 0 0 L 10 5 L 0 10 z" fill="#ef4444"/></marker>' +
    '</defs>'
  );
  /* Draw edges first (so nodes paint on top) */
  edges.forEach(function (e) {
    var p1 = positions[e.source];
    var p2 = positions[e.target];
    if (!p1 || !p2) return;
    /* Offset bidirectional pairs */
    var pair = edgeKey(e);
    var reverse = e.target + "→" + e.source;
    var sign = 0;
    if (seen[reverse]) sign = -1;
    seen[pair] = true;
    var d = _edgePath(p1, p2, sign);
    var color = e.status === "ok" ? "#4ecdc4" : "#ef4444";
    var dash = e.status === "ok" ? "" : 'stroke-dasharray="4 4"';
    var marker = e.status === "ok" ? "url(#arrow-ok)" : "url(#arrow-fail)";
    svgParts.push(
      '<path d="' + d + '" stroke="' + color + '" stroke-width="1.5" fill="none" ' +
      dash + ' marker-end="' + marker + '" opacity="0.75">' +
      '<title>' + escapeHtml(e.source) + ' → ' + escapeHtml(e.target) +
      ' (' + escapeHtml(e.status) + ', ' + escapeHtml(e.method) + ')</title>' +
      '</path>'
    );
  });
  /* Draw nodes */
  nodes.forEach(function (n) {
    var p = positions[n.id];
    if (!p) return;
    svgParts.push(
      '<g class="conn-node">' +
      '<circle cx="' + p.x + '" cy="' + p.y + '" r="' + nodeR + '" ' +
      'fill="#141414" stroke="#4ecdc4" stroke-width="2"/>' +
      '<text x="' + p.x + '" y="' + (p.y + 4) + '" text-anchor="middle" ' +
      'class="conn-node-label">' + escapeHtml(n.label) + '</text>' +
      '<title>' + escapeHtml(n.label) + ' — ' + escapeHtml(n.role || "") + '</title>' +
      '</g>'
    );
  });
  svgParts.push("</svg>");

  /* Build the legend + summary */
  var okCount = edges.filter(function (e) { return e.status === "ok"; }).length;
  var failCount = edges.filter(function (e) { return e.status === "fail"; }).length;
  var srcLabel = connectivityCache.source === "live" ? "live" : "static";
  var html =
    '<div class="connectivity-header">' +
    '<span class="connectivity-title">SSH mesh</span>' +
    '<span class="connectivity-summary">' +
    '<span class="conn-pill conn-pill-ok">' + okCount + ' reachable</span>' +
    '<span class="conn-pill conn-pill-fail">' + failCount + ' blocked</span>' +
    '<span class="conn-source">(' + escapeHtml(srcLabel) + ')</span>' +
    '</span>' +
    '</div>' +
    svgParts.join("");
  container.innerHTML = html;
}

/* Wire up: refresh when Machines tab opens */
document.addEventListener("DOMContentLoaded", function () {
  var btn = document.querySelector('[data-tab="resources"]');
  if (btn) {
    btn.addEventListener("click", fetchConnectivity);
  }
  /* Also refresh every 60s in case basilisk later replaces hardcode with live data */
  setInterval(function () {
    if (connectivityCache) fetchConnectivity();
  }, 60000);
});
