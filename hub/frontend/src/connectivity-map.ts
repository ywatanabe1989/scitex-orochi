// @ts-nocheck
// Migrated classic-script file. Types intentionally loose during
// the big-bang JS-to-TS bundle migration. Narrow later, per-file.
/* Connectivity map — SSH mesh visualization in Machines tab */
/* globals: apiUrl, escapeHtml */

var connectivityCache = null;

/* todo#51: bidirectional hover sync across SSH-mesh, res-cards,
 * activity-cards. Any DOM element with data-host-name / data-machine
 * matching `host` gets `.mesh-hl`; removed on `off`. Exposed globally so
 * activity-tab.js and resources-tab.js can call it without a circular
 * require. */
function syncHostHover(host, on) {
  if (!host) return;
  var selectors = [
    '.conn-node[data-host-name="' + host + '"]',
    '.res-card[data-host-name="' + host + '"]',
    '.activity-card[data-machine="' + host + '"]',
  ];
  selectors.forEach(function (sel) {
    var els;
    try {
      els = document.querySelectorAll(sel);
    } catch (e) {
      return;
    }
    els.forEach(function (el) {
      if (on) el.classList.add("mesh-hl");
      else el.classList.remove("mesh-hl");
    });
  });
}
window.syncHostHover = syncHostHover;

async function fetchConnectivity() {
  try {
    var res = await fetch(apiUrl("/api/connectivity/"), {
      credentials: "same-origin",
    });
    if (!res.ok) return;
    connectivityCache = await res.json();
    renderConnectivityMap();
  } catch (e) {
    console.warn("fetchConnectivity error:", e);
  }
}

/* Layout: machine nodes on inner ring, bastion nodes on outer ring, aligned to host */
function _layoutNodes(nodes, cx, cy, innerRadius, outerRadius) {
  var positions = {};
  if (nodes.length === 0) return positions;
  var machines = nodes.filter(function (n) {
    return n.type !== "bastion";
  });
  var bastions = nodes.filter(function (n) {
    return n.type === "bastion";
  });
  var mCount = machines.length;

  /* Machine nodes: evenly around inner ring */
  for (var i = 0; i < mCount; i++) {
    var theta = -Math.PI / 2 + (2 * Math.PI * i) / mCount;
    positions[machines[i].id] = {
      x: cx + innerRadius * Math.cos(theta),
      y: cy + innerRadius * Math.sin(theta),
    };
  }
  /* Bastion nodes: outer ring, aligned behind their host machine */
  bastions.forEach(function (b) {
    var hostPos = positions[b.host];
    if (hostPos) {
      /* Push outward from center through the host */
      var dx = hostPos.x - cx;
      var dy = hostPos.y - cy;
      var len = Math.sqrt(dx * dx + dy * dy) || 1;
      positions[b.id] = {
        x: cx + (outerRadius * dx) / len,
        y: cy + (outerRadius * dy) / len,
      };
    } else {
      /* Fallback: place at bottom */
      positions[b.id] = { x: cx, y: cy + outerRadius };
    }
  });
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
  return (
    "M " +
    (p1.x + nx * off) +
    " " +
    (p1.y + ny * off) +
    " Q " +
    midx +
    " " +
    midy +
    " " +
    (p2.x + nx * off) +
    " " +
    (p2.y + ny * off)
  );
}

function renderConnectivityMap() {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var container = document.getElementById("connectivity-map");
  if (!container) return;
  if (
    !connectivityCache ||
    !connectivityCache.nodes ||
    connectivityCache.nodes.length === 0
  ) {
    container.innerHTML = '<p class="empty-notice">No connectivity data.</p>';
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try {
        msgInput.setSelectionRange(savedStart, savedEnd);
      } catch (_) {}
    }
    return;
  }
  var nodes = connectivityCache.nodes;
  var edges = connectivityCache.edges || [];
  var W = 520;
  var H = 420;
  var cx = W / 2;
  var cy = H / 2;
  var innerRadius = 100;
  var outerRadius = 190;
  var nodeR = 26;
  var bastionR = 20;
  var positions = _layoutNodes(nodes, cx, cy, innerRadius, outerRadius);

  /* Pair up bidirectional edges so we can offset them */
  var edgeKey = function (e) {
    return e.source + "→" + e.target;
  };
  var seen = {};

  var svgParts = [];
  svgParts.push(
    '<svg class="connectivity-svg" viewBox="0 0 ' +
      W +
      " " +
      H +
      '" width="100%" height="' +
      H +
      '">',
  );
  /* Definitions: arrowhead markers */
  svgParts.push(
    "<defs>" +
      '<marker id="arrow-ok" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">' +
      '<path d="M 0 0 L 10 5 L 0 10 z" fill="#4ecdc4"/></marker>' +
      '<marker id="arrow-fail" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">' +
      '<path d="M 0 0 L 10 5 L 0 10 z" fill="#ef4444"/></marker>' +
      '<marker id="arrow-pending" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">' +
      '<path d="M 0 0 L 10 5 L 0 10 z" fill="#f59e0b"/></marker>' +
      "</defs>",
  );
  /* Separate machine vs bastion nodes */
  var machineNodes = nodes.filter(function (n) {
    return n.type !== "bastion";
  });
  var bastionNodes = nodes.filter(function (n) {
    return n.type === "bastion";
  });
  /* Separate bastion-anchor edges from machine-to-machine edges */
  var bastionAnchorEdges = edges.filter(function (e) {
    return (
      e.source.indexOf("bastion") === 0 || e.target.indexOf("bastion") === 0
    );
  });
  var machineEdges = edges.filter(function (e) {
    return (
      e.source.indexOf("bastion") !== 0 && e.target.indexOf("bastion") !== 0
    );
  });

  /* Draw bastion anchor edges (dashed, thin) first */
  bastionAnchorEdges.forEach(function (e) {
    var p1 = positions[e.source];
    var p2 = positions[e.target];
    if (!p1 || !p2) return;
    var color =
      e.status === "ok"
        ? "#4ecdc4"
        : e.status === "pending"
          ? "#f59e0b"
          : "#ef4444";
    var d = "M " + p1.x + " " + p1.y + " L " + p2.x + " " + p2.y;
    svgParts.push(
      '<path d="' +
        d +
        '" stroke="' +
        color +
        '" stroke-width="1" fill="none" ' +
        'stroke-dasharray="3 3" opacity="0.5">' +
        "<title>" +
        escapeHtml(e.source) +
        " ↔ " +
        escapeHtml(e.target) +
        " (CF tunnel)</title>" +
        "</path>",
    );
  });

  /* Draw machine-to-machine edges */
  machineEdges.forEach(function (e) {
    var p1 = positions[e.source];
    var p2 = positions[e.target];
    if (!p1 || !p2) return;
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
      '<path d="' +
        d +
        '" stroke="' +
        color +
        '" stroke-width="1.5" fill="none" ' +
        dash +
        ' marker-end="' +
        marker +
        '" opacity="0.75">' +
        "<title>" +
        escapeHtml(e.source) +
        " → " +
        escapeHtml(e.target) +
        " (" +
        escapeHtml(e.status) +
        ", " +
        escapeHtml(e.method) +
        ")</title>" +
        "</path>",
    );
  });

  /* Draw bastion nodes (cloud/diamond shape on outer ring) */
  bastionNodes.forEach(function (n) {
    var p = positions[n.id];
    if (!p) return;
    var isPending = n.status === "pending";
    var stroke = isPending ? "#f59e0b" : "#4ecdc4";
    var fill = isPending ? "rgba(245,158,11,0.12)" : "rgba(78,205,196,0.10)";
    svgParts.push(
      '<g class="conn-node conn-node-bastion">' +
        '<rect x="' +
        (p.x - bastionR) +
        '" y="' +
        (p.y - bastionR * 0.7) +
        '" ' +
        'width="' +
        bastionR * 2 +
        '" height="' +
        bastionR * 1.4 +
        '" rx="8" ry="8" ' +
        'fill="' +
        fill +
        '" stroke="' +
        stroke +
        '" stroke-width="1.5" ' +
        (isPending ? 'stroke-dasharray="4 2"' : "") +
        "/>" +
        '<text x="' +
        p.x +
        '" y="' +
        (p.y + 3) +
        '" text-anchor="middle" ' +
        'class="conn-node-label conn-bastion-label">' +
        "☁ " +
        escapeHtml(n.label.replace("bastion-", "")) +
        "</text>" +
        "<title>" +
        escapeHtml(n.label) +
        " — " +
        escapeHtml(n.role || "") +
        "</title>" +
        "</g>",
    );
  });

  /* Draw machine nodes (inner ring) */
  machineNodes.forEach(function (n) {
    var p = positions[n.id];
    if (!p) return;
    /* todo#51: data-host-name lets hover-sync find the node from res-card
     * and activity-card mouseenter handlers. Use n.id (matches .res-card
     * data-host-name and .activity-card data-machine). */
    svgParts.push(
      '<g class="conn-node" data-host-name="' +
        escapeHtml(n.id) +
        '">' +
        '<circle cx="' +
        p.x +
        '" cy="' +
        p.y +
        '" r="' +
        nodeR +
        '" ' +
        'fill="#141414" stroke="#4ecdc4" stroke-width="2"/>' +
        '<text x="' +
        p.x +
        '" y="' +
        (p.y + 4) +
        '" text-anchor="middle" ' +
        'class="conn-node-label">' +
        escapeHtml(n.label) +
        "</text>" +
        "<title>" +
        escapeHtml(n.label) +
        " — " +
        escapeHtml(n.role || "") +
        "</title>" +
        "</g>",
    );
  });
  svgParts.push("</svg>");

  /* Build the legend + summary */
  var okCount = edges.filter(function (e) {
    return e.status === "ok";
  }).length;
  var failCount = edges.filter(function (e) {
    return e.status === "fail";
  }).length;
  var pendingCount = edges.filter(function (e) {
    return e.status === "pending";
  }).length;
  var bastionLive = nodes.filter(function (n) {
    return n.type === "bastion" && n.status !== "pending";
  }).length;
  var bastionTotal = nodes.filter(function (n) {
    return n.type === "bastion";
  }).length;
  var srcLabel = connectivityCache.source === "live" ? "live" : "static";
  var pendingPill =
    pendingCount > 0
      ? '<span class="conn-pill conn-pill-pending">☁ ' +
        bastionLive +
        "/" +
        bastionTotal +
        " CF tunnels</span>"
      : '<span class="conn-pill conn-pill-ok">☁ ' +
        bastionLive +
        "/" +
        bastionTotal +
        " CF tunnels</span>";
  var html =
    '<div class="connectivity-header">' +
    '<span class="connectivity-title">SSH mesh</span>' +
    '<span class="connectivity-summary">' +
    pendingPill +
    '<span class="conn-pill conn-pill-ok">' +
    okCount +
    " links ok</span>" +
    (failCount
      ? '<span class="conn-pill conn-pill-fail">' +
        failCount +
        " blocked</span>"
      : "") +
    '<span class="conn-source">(' +
    escapeHtml(srcLabel) +
    ")</span>" +
    "</span>" +
    "</div>" +
    svgParts.join("");
  container.innerHTML = html;
  /* todo#51: after innerHTML swap, re-attach hover handlers on each
   * machine node. Delegation via the SVG root is awkward because the
   * event target is the inner <circle> or <text>. */
  Array.prototype.forEach.call(
    container.querySelectorAll(".conn-node[data-host-name]"),
    function (g) {
      var host = g.getAttribute("data-host-name");
      g.addEventListener("mouseenter", function (ev) {
        syncHostHover(host, true);
        /* todo#86: show CPU/RAM/GPU/VRAM/Disk tooltip on machine node hover. */
        if (typeof showMachineTooltip === "function")
          showMachineTooltip(host, ev);
      });
      g.addEventListener("mousemove", function (ev) {
        if (typeof moveMachineTooltip === "function") moveMachineTooltip(ev);
      });
      g.addEventListener("mouseleave", function () {
        syncHostHover(host, false);
        if (typeof hideMachineTooltip === "function") hideMachineTooltip();
      });
    },
  );
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
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
