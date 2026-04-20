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

  /* Build all four LED <circle> elements in canonical order (WS, Ping,
   * Local-FN, Remote-Echo). Returns the concatenated SVG string.
   * Mirrors renderAgentLeds() in agent-badge.js 1:1 — same state inputs,
   * same color conventions. First LED is centered at startCx; successive
   * LEDs step by (2*LED_R + GAP). */
  function _renderAgentBadgeLedsSvg(a, startCx, y, LED_R, GAP, opts) {
    var connectedFlag = _connected(a);
    var liveness =
      a.liveness || a.status || (connectedFlag ? "online" : "offline");
    var FN_COLORS = {
      online: "#4ecdc4",
      idle: "#ffd93d",
      stale: "#ff8c42",
      offline: "#555",
      waiting: "#60a5fa",
      auth_error: "#ef4444",
    };

    // 1. WS
    var wsColor = connectedFlag ? "#4ecdc4" : "#555";
    // 2. Ping — from last_pong_ts age (<60s green, <180s warn, else off).
    var pong = a.last_pong_ts;
    var pongAge =
      pong != null ? (Date.now() - new Date(pong).getTime()) / 1000 : null;
    var pingColor = "#555";
    var pingLabel = "no pong yet";
    if (pongAge != null) {
      if (pongAge < 60) {
        pingColor = "#4ecdc4";
        pingLabel = "pong " + Math.round(pongAge) + "s ago";
      } else if (pongAge < 180) {
        pingColor = "#ffd93d";
        pingLabel = "stale pong " + Math.round(pongAge) + "s ago";
      } else {
        pingColor = "#555";
        pingLabel = "no recent pong (" + Math.round(pongAge) + "s)";
      }
    }
    // 3. Local functional state.
    var fnColor = FN_COLORS[liveness] || "#555";
    if (opts.isDead) fnColor = "#ef4444";
    // 4. Remote echo — from last_nonce_echo_at age.
    var echo = a.last_nonce_echo_at;
    var echoAge =
      echo != null ? (Date.now() - new Date(echo).getTime()) / 1000 : null;
    var echoColor = "#555";
    var echoLabel = "not yet probed by any peer";
    if (echoAge != null) {
      if (echoAge < 90) {
        echoColor = "#4ecdc4";
        echoLabel = "echoed " + Math.round(echoAge) + "s ago";
      } else if (echoAge < 300) {
        echoColor = "#ffd93d";
        echoLabel = "stale echo " + Math.round(echoAge) + "s ago";
      } else {
        echoColor = "#ef4444";
        echoLabel = "no echo (" + Math.round(echoAge) + "s)";
      }
    }

    var leds = [
      {
        color: wsColor,
        title: "WebSocket: " + (connectedFlag ? "connected" : "disconnected"),
      },
      { color: pingColor, title: "Ping: " + pingLabel },
      { color: fnColor, title: "Liveness: " + liveness },
      { color: echoColor, title: "Remote echo: " + echoLabel },
    ];
    var out = "";
    var step = 2 * LED_R + GAP;
    for (var i = 0; i < leds.length; i++) {
      var cx = startCx + i * step;
      out +=
        '<circle cx="' +
        cx.toFixed(1) +
        '" cy="' +
        y.toFixed(1) +
        '" r="' +
        LED_R +
        '" fill="' +
        leds[i].color +
        '" stroke="#0a0a0a" stroke-width="0.5"><title>' +
        _escape(leds[i].title) +
        "</title></circle>";
    }
    return { svg: out, width: (leds.length - 1) * step + 2 * LED_R };
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
    var GAP = 3;

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

    /* Canonical layout per ywatanabe 2026-04-20:
     *   icon + 4 LEDs + name@hostname + star
     * All elements laid out left→right starting at glyphX. Human nodes
     * keep their simpler icon+name layout (no LEDs, no star slot). */
    var iconHalf = iconSize / 2;
    var ledsWidth = 0;
    var ledBlock = { svg: "", width: 0 };

    // Position the glyph (icon). For human: centered around x. For agent:
    // leftmost element, with its CENTER at glyphX.
    var glyphX;
    if (opts.isHuman) {
      glyphX = x - 10;
    } else {
      // Pack icon + 4 LEDs + name + star starting from glyphX, centering
      // the whole cluster around pos.x. Compute total width first.
      glyphX = x; // temp; will reposition below
    }

    // Compute LED block width (4 LEDs spaced by 2*R+GAP).
    var ledStep = 2 * LED_R + GAP;
    if (showLeds) {
      ledsWidth = 3 * ledStep + 2 * LED_R; // 4 LEDs span
    }

    var textW = Math.max(40, nameText.length * 6.5);
    var starW = showStar ? 14 : 0;

    if (!opts.isHuman) {
      // Total width: icon + gap + LEDs + gap + name + gap + star.
      var GAP_BETWEEN = 6;
      var total =
        iconSize +
        GAP_BETWEEN +
        ledsWidth +
        GAP_BETWEEN +
        textW +
        (showStar ? GAP_BETWEEN + starW : 0);
      // Re-center: cluster centered on pos.x.
      var clusterLeft = x - total / 2;
      glyphX = clusterLeft + iconHalf; // center of icon
      var ledsStartCx = glyphX + iconHalf + GAP_BETWEEN + LED_R;
      var nameX = ledsStartCx + ledsWidth - LED_R + GAP_BETWEEN;
      var starX = nameX + textW + GAP_BETWEEN;

      var glyph = _renderAgentGlyphSvg(a, glyphX, y, iconSize, ident, opts);

      if (showLeds) {
        ledBlock = _renderAgentBadgeLedsSvg(
          a,
          ledsStartCx,
          y,
          LED_R,
          GAP,
          opts,
        );
      }

      var starSvg = "";
      if (showStar) {
        var pinned = !!a.pinned;
        starSvg =
          '<text class="topo-label-pin topo-agent-star" x="' +
          starX.toFixed(1) +
          '" y="' +
          (y + 4).toFixed(1) +
          '" fill="' +
          (pinned ? "#fbbf24" : "#3a3a3a") +
          '" font-size="13" style="cursor:pointer" data-pin-name="' +
          _escape(a.name || "") +
          '" data-pin-next="' +
          (pinned ? "false" : "true") +
          '"><title>' +
          _escape(pinned ? "Unstar" : "Star") +
          "</title>" +
          (pinned ? "\u2605" : "\u2606") +
          "</text>";
      }

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

      var badgeLeft = clusterLeft - 4;
      var badgeWidth = total + 8;
      var badgeY = y - 11;
      var bg =
        '<rect class="topo-agent-bg" x="' +
        badgeLeft.toFixed(1) +
        '" y="' +
        badgeY.toFixed(1) +
        '" width="' +
        badgeWidth.toFixed(1) +
        '" height="22" rx="11" ry="11"/>';

      var cls = "topo-node topo-agent";
      if (opts.isSelected) cls += " topo-agent-selected";
      if (opts.isDead) cls += " topo-agent-dead";
      if (opts.extraClass) cls += " " + opts.extraClass;

      /* Order matches the HTML agent-badge.js canonical order:
       *   icon + 4 LEDs + name + star. */
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
        ledBlock.svg +
        nameSvg +
        starSvg +
        "</g>"
      );
    }

    // ── Human node branch (simpler layout; no LEDs, no star). ─────────
    var hGlyph = _renderAgentGlyphSvg(a, glyphX, y, iconSize, ident, opts);
    var hNameX = x + 6;
    var hTextW = Math.max(40, nameText.length * 6.5);
    var hBadgeLeft = x - 18;
    var hBadgeRight = hNameX + hTextW + 6;
    var hBadgeWidth = hBadgeRight - hBadgeLeft;
    var hBadgeY = y - 11;
    var hBg =
      '<rect class="topo-agent-bg topo-human-bg" x="' +
      hBadgeLeft.toFixed(1) +
      '" y="' +
      hBadgeY.toFixed(1) +
      '" width="' +
      hBadgeWidth.toFixed(1) +
      '" height="22" rx="11" ry="11"/>';
    var hNameSvg = "";
    if (showName) {
      hNameSvg =
        '<text class="topo-label topo-label-agent" x="' +
        hNameX.toFixed(1) +
        '" y="' +
        (y + 4).toFixed(1) +
        '" fill="' +
        color +
        '">' +
        _escape(nameText) +
        "</text>";
    }
    var hCls = "topo-node topo-agent topo-human";
    if (opts.isSelected) hCls += " topo-agent-selected";
    if (opts.extraClass) hCls += " " + opts.extraClass;
    return (
      '<g class="' +
      hCls +
      '" data-agent="' +
      _escape(a.name || "") +
      '">' +
      "<title>" +
      _escape(ident.tooltip || a.name || "") +
      "</title>" +
      hBg +
      hGlyph +
      hNameSvg +
      "</g>"
    );
  }

  window.renderAgentBadgeSvg = renderAgentBadgeSvg;
})();
