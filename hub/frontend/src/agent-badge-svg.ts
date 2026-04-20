/**
 * agent-badge-svg.js — SVG (topology-canvas) renderer parallel to
 * renderAgentBadge() in agent-badge.js. Split out so agent-badge.js
 * stays under the 512-line .js hook cap.
 *
 * Exports (window-scoped):
 *   renderAgentBadgeSvg(a, pos, opts) — agent / human node <g> group
 *
 * Emits a <g class="topo-node topo-agent" data-agent="..."> with the
 * same state model as the HTML badge: icon + star + 2 LEDs (WS/FN)
 * + name label. Preserves every CSS hook the canvas uses today:
 *   .topo-agent, .topo-agent-bg, .topo-agent-dead, .topo-label,
 *   .topo-human, .topo-human-bg, .topo-human-glyph, .topo-agent-glyph.
 *
 * pos = {x, y, r?}; r optional, default 12 — matches ring layout.
 * opts (all optional):
 *   isDead       — add .topo-agent-dead + red FN LED
 *   isSelected   — add .topo-agent-selected
 *   isHuman      — gold pill (.topo-human) + 👤 icon, no LEDs
 *   showName     — render text label (default true)
 *   showStar     — render star slot when pinned (default true)
 *   showLeds     — render WS+FN LED pair (default true; skipped for human)
 *   extraClass   — appended to outer <g> classList
 *   iconSize     — glyph/image px (default 14)
 *   labelOverride — override display-name (human node passes humanName)
 *
 * Hard rule: if you need a new variant, add an opt — never inline a
 * different SVG markup. dashboard-development-discipline.md rule 1.
 */

(function () {
  "use strict";

  function _escape(s) {
    if (typeof escapeHtml === "function") return escapeHtml(s);
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[
          c
        ] || c
      );
    });
  }

  function _connected(a) {
    if (typeof connected === "function") return connected(a);
    return (a.status || "online") !== "offline";
  }

  // Glyph cascade helper — image URL > emoji > snake SVG > 👤 fallback.
  // Shared between agent and human branches so the cascade stays
  // identical across the two node shapes.
  function _renderAgentGlyphSvg(a, gx, gy, size, ident, opts) {
    opts = opts || {};
    var cacheMap;
    if (opts.isHuman) {
      cacheMap =
        typeof cachedHumanIcons !== "undefined" ? cachedHumanIcons : {};
    } else {
      cacheMap =
        typeof cachedAgentIcons !== "undefined" ? cachedAgentIcons : {};
    }
    var cached = (cacheMap && cacheMap[a.name]) || "";
    var isUrl =
      cached && (cached.indexOf("http") === 0 || cached.indexOf("/") === 0);
    if (isUrl) {
      return (
        '<image class="topo-agent-glyph-img' +
        (opts.isHuman ? " topo-human-glyph topo-human-glyph-img" : "") +
        '" href="' +
        _escape(cached) +
        '" x="' +
        (gx - size / 2).toFixed(1) +
        '" y="' +
        (gy - size / 2).toFixed(1) +
        '" width="' +
        size +
        '" height="' +
        size +
        '" preserveAspectRatio="xMidYMid slice"/>'
      );
    }
    if (cached) {
      // User-assigned emoji.
      return (
        '<text class="' +
        (opts.isHuman ? "topo-human-glyph" : "topo-agent-glyph") +
        '" x="' +
        gx.toFixed(1) +
        '" y="' +
        (opts.isHuman ? (gy + 4).toFixed(1) : gy.toFixed(1)) +
        '" font-size="' +
        (opts.isHuman ? 13 : 12) +
        '"' +
        (opts.isHuman
          ? ""
          : ' dominant-baseline="central" text-anchor="middle"') +
        ">" +
        cached +
        "</text>"
      );
    }
    if (opts.isHuman) {
      return (
        '<text class="topo-human-glyph" x="' +
        gx.toFixed(1) +
        '" y="' +
        (gy + 4).toFixed(1) +
        '" font-size="13">\uD83D\uDC64</text>'
      );
    }
    // Default agent glyph: scitex S-shaped snake SVG from agent-icons.js
    // (single source of truth — user directive 2026-04-20 "please use
    // central, single-source-of-icons"). Inject x/y into the returned
    // <svg> so it lands at gx,gy inside the parent canvas.
    var color =
      (ident && ident.color) ||
      (typeof getAgentColor === "function"
        ? getAgentColor(a.name || "")
        : "#4ecdc4");
    var markup =
      typeof getSnakeIcon === "function" ? getSnakeIcon(size, color) : "";
    return markup.replace(
      /<svg /,
      '<svg x="' +
        (gx - size / 2).toFixed(1) +
        '" y="' +
        (gy - size / 2).toFixed(1) +
        '" ',
    );
  }

  function renderAgentBadgeSvg(a, pos, opts) {
    opts = opts || {};
    var x = pos.x;
    var y = pos.y;
    var showName = opts.showName !== false;
    var showStar = opts.showStar !== false;
    var showLeds = opts.showLeds !== false && !opts.isHuman;
    var iconSize = opts.iconSize || 14;
    var LED_R = 4;
    var GAP = 5;

    var ident =
      typeof agentIdentity === "function"
        ? agentIdentity(a)
        : {
            color:
              typeof getAgentColor === "function"
                ? getAgentColor(a.name || "")
                : "#4ecdc4",
            displayName: a.name || "",
            tooltip: a.name || "",
          };
    var nameText = opts.labelOverride || ident.displayName || a.name || "";
    var color = opts.isHuman ? "#fbbf24" : ident.color;

    var glyphX = opts.isHuman ? x - 10 : x - LED_R - GAP / 2 - 28;
    var glyph = _renderAgentGlyphSvg(a, glyphX, y, iconSize, ident, opts);

    // LEDs — two circles centered on the ring slot (WS left, FN right).
    var wsLed = "";
    var fnLed = "";
    if (showLeds) {
      var connectedFlag = _connected(a);
      var liveness =
        a.liveness || a.status || (connectedFlag ? "online" : "offline");
      var FN_COLORS = {
        online: "#4ecdc4",
        idle: "#ffd93d",
        stale: "#ff8c42",
        offline: "#555",
      };
      var wsColor = connectedFlag ? "#4ecdc4" : "#555";
      var fnColor = FN_COLORS[liveness] || "#555";
      if (opts.isDead) fnColor = "#ef4444";
      var wsCx = x - (LED_R + GAP / 2);
      var fnCx = x + (LED_R + GAP / 2);
      wsLed =
        '<circle cx="' +
        wsCx.toFixed(1) +
        '" cy="' +
        y.toFixed(1) +
        '" r="' +
        LED_R +
        '" fill="' +
        wsColor +
        '" stroke="#0a0a0a" stroke-width="0.5"><title>WebSocket: ' +
        (connectedFlag ? "connected" : "disconnected") +
        "</title></circle>";
      fnLed =
        '<circle cx="' +
        fnCx.toFixed(1) +
        '" cy="' +
        y.toFixed(1) +
        '" r="' +
        LED_R +
        '" fill="' +
        fnColor +
        '" stroke="#0a0a0a" stroke-width="0.5"><title>Liveness: ' +
        _escape(liveness) +
        "</title></circle>";
    }

    var pinMark = "";
    if (showStar && a.pinned) {
      pinMark =
        '<text class="topo-label-pin" x="' +
        (x + LED_R + GAP / 2 + 8).toFixed(1) +
        '" y="' +
        (y + 4).toFixed(1) +
        '" fill="#fbbf24" font-size="13">\u2605</text>';
    }

    var nameX = opts.isHuman ? x + 6 : x + LED_R + GAP / 2 + 22;
    var textW = Math.max(40, nameText.length * 6.5);

    var badgeLeft = opts.isHuman ? x - 18 : glyphX - 14;
    var badgeRight = nameX + textW + 6;
    var badgeWidth = badgeRight - badgeLeft;
    var badgeY = y - 11;
    var bgClass = opts.isHuman
      ? "topo-agent-bg topo-human-bg"
      : "topo-agent-bg";
    var bg =
      '<rect class="' +
      bgClass +
      '" x="' +
      badgeLeft.toFixed(1) +
      '" y="' +
      badgeY.toFixed(1) +
      '" width="' +
      badgeWidth.toFixed(1) +
      '" height="22" rx="11" ry="11"/>';

    var nameSvg = "";
    if (showName) {
      nameSvg =
        '<text class="topo-label topo-label-agent" x="' +
        nameX.toFixed(1) +
        '" y="' +
        (y + 4).toFixed(1) +
        '" fill="' +
        color +
        '">' +
        _escape(nameText) +
        "</text>";
    }

    var cls = "topo-node topo-agent";
    if (opts.isHuman) cls += " topo-human";
    if (opts.isSelected) cls += " topo-agent-selected";
    if (opts.isDead) cls += " topo-agent-dead";
    if (opts.extraClass) cls += " " + opts.extraClass;

    return (
      '<g class="' +
      cls +
      '" data-agent="' +
      _escape(a.name || "") +
      '">' +
      "<title>" +
      _escape(ident.tooltip || a.name || "") +
      "</title>" +
      bg +
      glyph +
      wsLed +
      fnLed +
      pinMark +
      nameSvg +
      "</g>"
    );
  }

  window.renderAgentBadgeSvg = renderAgentBadgeSvg;
})();
