/* activity-tab/topology-nodes.js — SVG emission for channel diamonds,
 * agent pills, and the human user node. */


function _topoBuildChannelsSvg(visible, channels, chPos, chSet, _chPrefs) {
  /* Per-channel subscriber counts across the visible agents. Used to
   * scale each channel diamond — "based on the number of agents, the
   * channel node can be larger" (ywatanabe 2026-04-19). */
  var chAgentCounts = {};
  visible.forEach(function (a) {
    (a.channels || []).forEach(function (c) {
      if (!chSet[c]) return;
      chAgentCounts[c] = (chAgentCounts[c] || 0) + 1;
    });
  });
  /* Channel diamonds (rotated squares) with label above. Size scales
   * per user-selected "size:" dropdown (todo#95):
   *   equal       — fixed r = 12
   *   subscribers — r = 8 + sqrt(count-1)*5, clamped [8,22]
   *   posts       — reserved; /api/stats does not yet expose post counts,
   *                 falls through to equal until backend support lands
   * sqrt is chosen over linear so visual AREA grows sub-linearly and one
   * busy hub doesn't overpower the layout. */
  var chSvg = channels
    .map(function (c) {
      var p = chPos[c];
      var count = chAgentCounts[c] || 1;
      var r;
      if (_topoSizeBy === "subscribers") {
        r = Math.min(22, 8 + Math.sqrt(Math.max(0, count - 1)) * 5);
      } else {
        /* equal + posts (deferred) */
        r = 12;
      }
      var labelText = c + " (" + count + ")";
      var pts =
        p.x +
        "," +
        (p.y - r) +
        " " +
        (p.x + r) +
        "," +
        p.y +
        " " +
        p.x +
        "," +
        (p.y + r) +
        " " +
        (p.x - r) +
        "," +
        p.y;
      var _pref = _chPrefs[c] || {};
      var chCls = " topo-node topo-channel";
      if (_pref.is_starred) chCls += " topo-channel-starred";
      if (_pref.is_muted) chCls += " topo-channel-muted";
      var starGlyph = _pref.is_starred
        ? '<text class="topo-ch-star" x="' +
          (p.x + r + 2).toFixed(1) +
          '" y="' +
          (p.y - r + 4).toFixed(1) +
          '" font-size="11" fill="#fbbf24">★</text>'
        : "";
      var muteGlyph = _pref.is_muted
        ? '<text class="topo-ch-mute" x="' +
          (p.x - r - 12).toFixed(1) +
          '" y="' +
          (p.y - r + 4).toFixed(1) +
          '" font-size="9" fill="#94a3b8">\uD83D\uDD15</text>'
        : "";
      /* Custom channel icon — cascade: image URL → emoji → no glyph.
       * Symmetric to the agent canvas glyph in the same file: URL
       * renders via <image>; emoji via <text>. todo#101 entity
       * consistency. */
      var iconGlyph = "";
      var _ci =
        typeof cachedChannelIcons !== "undefined"
          ? cachedChannelIcons[c] || ""
          : "";
      var _ciIsUrl =
        _ci && (_ci.indexOf("http") === 0 || _ci.indexOf("/") === 0);
      if (_ciIsUrl) {
        var _chImg = Math.max(14, Math.round(r * 1.6));
        iconGlyph =
          '<image class="topo-ch-icon-img" href="' +
          escapeHtml(_ci) +
          '" x="' +
          (p.x - _chImg / 2).toFixed(1) +
          '" y="' +
          (p.y - _chImg / 2).toFixed(1) +
          '" width="' +
          _chImg +
          '" height="' +
          _chImg +
          '" preserveAspectRatio="xMidYMid slice"/>';
      } else if (_ci) {
        iconGlyph =
          '<text class="topo-ch-emoji" x="' +
          p.x.toFixed(1) +
          '" y="' +
          (p.y + 4).toFixed(1) +
          '" font-size="' +
          Math.max(11, Math.round(r * 1.2)) +
          '" text-anchor="middle" dominant-baseline="middle">' +
          _ci +
          "</text>";
      }
      return (
        '<g class="' +
        chCls +
        '" data-channel="' +
        escapeHtml(c) +
        '" data-agent-count="' +
        count +
        '">' +
        '<polygon points="' +
        pts +
        '" fill="#1a1a1a" stroke="#444" stroke-width="1"/>' +
        iconGlyph +
        starGlyph +
        muteGlyph +
        /* Bordered badge behind the channel label — matches the
         * agent pill aesthetic so channels read as first-class
         * identities (user 2026-04-20: "channels are not shown in
         * badges? bordered identities"). Width estimated from label
         * length; centered horizontally above the diamond. */
        (function () {
          var _chLabelW = Math.max(40, labelText.length * 6.5);
          var _chLabelX = p.x - _chLabelW / 2 - 6;
          var _chLabelY = p.y - r - 18;
          return (
            '<rect class="topo-channel-bg" x="' +
            _chLabelX.toFixed(1) +
            '" y="' +
            _chLabelY.toFixed(1) +
            '" width="' +
            (_chLabelW + 12).toFixed(1) +
            '" height="20" rx="10" ry="10"/>'
          );
        })() +
        '<text class="topo-label topo-label-ch" x="' +
        p.x +
        '" y="' +
        (p.y - r - 4).toFixed(1) +
        '" text-anchor="middle">' +
        escapeHtml(labelText) +
        "</text>" +
        "</g>"
      );
    })
    .join("");

  return chSvg;
}

function _topoBuildAgentsSvg(visible, agentPos) {
  /* Agent nodes — no big identity disc (the disc + two LEDs read as a
   * "face", ywatanabe 2026-04-19). Just the twin-LED pair the list
   * view uses — WS on the left, functional liveness on the right —
   * followed by the agent name (identity color goes on the text).
   * Pinned agents get a small gold pushpin prefix instead of a ring. */
  var FN_COLORS = {
    online: "#4ecdc4",
    idle: "#ffd93d",
    stale: "#ff8c42",
    offline: "#555",
  };
  var agentSvg = visible
    .map(function (a) {
      var p = agentPos[a.name];
      /* todo#96: shared identity helper — color + display-name +
       * tooltip come from the same source as the sidebar row and
       * pool chip so the SAME agent always looks the same. */
      var _ident =
        typeof agentIdentity === "function"
          ? agentIdentity(a)
          : {
              color: getAgentColor(_colorKeyFor(a)),
              displayName:
                typeof hostedAgentName === "function"
                  ? hostedAgentName(a)
                  : cleanAgentName
                    ? cleanAgentName(a.name)
                    : a.name,
              tooltip: a.name || "",
            };
      var color = _ident.color;
      var connected = (a.status || "online") !== "offline";
      var liveness =
        a.liveness || a.status || (connected ? "online" : "offline");
      /* Dead-state detection — heartbeat is fresh but the agent has
       * shown no reaction (no tool call, no recorded action) for
       * >3min. This catches the classic "silent death" where the
       * sidecar keeps heartbeating but the LLM process is gone.
       * ywatanabe 2026-04-19: "please implement dead color, red with
       * logics like 3 min no-reaction". */
      var toolSec =
        typeof _secondsSinceIso === "function"
          ? _secondsSinceIso(a.last_tool_at)
          : null;
      var actSec =
        typeof _secondsSinceIso === "function"
          ? _secondsSinceIso(a.last_action)
          : null;
      var noTool = toolSec == null || toolSec > 180;
      var noAct = actSec == null || actSec > 180;
      var isDead = connected && noTool && noAct;
      var wsColor = connected ? "#4ecdc4" : "#555";
      var fnColor = FN_COLORS[liveness] || "#555";
      if (isDead) fnColor = "#ef4444";
      var nameText = _ident.displayName;
      /* Two small LEDs centered on the ring position, then the label to
       * the right. Gap between LEDs = 10px so they read as a pair, not
       * a single smear. */
      var LED_R = 4;
      var GAP = 5;
      var wsCx = p.x - (LED_R + GAP / 2);
      var fnCx = p.x + (LED_R + GAP / 2);
      var wsLed =
        '<circle cx="' +
        wsCx.toFixed(1) +
        '" cy="' +
        p.y.toFixed(1) +
        '" r="' +
        LED_R +
        '" fill="' +
        wsColor +
        '" stroke="#0a0a0a" stroke-width="0.5"><title>WebSocket: ' +
        (connected ? "connected" : "disconnected") +
        "</title></circle>";
      var fnLed =
        '<circle cx="' +
        fnCx.toFixed(1) +
        '" cy="' +
        p.y.toFixed(1) +
        '" r="' +
        LED_R +
        '" fill="' +
        fnColor +
        '" stroke="#0a0a0a" stroke-width="0.5"><title>Liveness: ' +
        escapeHtml(liveness) +
        "</title></circle>";
      /* Always reserve the star slot so every canvas pill has the same
       * [icon][WS LED][FN LED][star][name] geometry — starred agents
       * show ★, others leave the slot blank. Keeps pill widths
       * consistent across the canvas (ywatanabe 2026-04-20: "cards in
       * the canvas look different than others"). */
      var pinMark = a.pinned
        ? '<text class="topo-label-pin" x="' +
          (p.x + LED_R + GAP / 2 + 8).toFixed(1) +
          '" y="' +
          (p.y + 4).toFixed(1) +
          '" fill="#fbbf24" font-size="13">\u2605</text>'
        : "";
      var nameX = p.x + LED_R + GAP / 2 + 22;
      var selCls = _topoSelected[a.name] ? " topo-agent-selected" : "";
      var deadCls = isDead ? " topo-agent-dead" : "";
      /* Button-like badge background so the agent reads as clickable.
       * Approx width from the rendered text + LEDs + optional pin. ch
       * width ≈ 6.5px at 11px monospace. ywatanabe 2026-04-19:
       * "agent nodes should be easily clickable, make them button-like
       * object would be better (surround them by small border, like a
       * bit of badge)" */
      /* Robot glyph prefix — agent identity icon, parallel to the human
       * node's 👤. Sits just inside the left edge of the pill with
       * ample gap before the two LEDs so the emoji doesn't overlap the
       * WebSocket indicator. ywatanabe 2026-04-19: "add icon to agents
       * with robotic one as well" / "add margins to icons and
       * indicators now overlapping". */
      var agentIconX = p.x - LED_R - GAP / 2 - 28;
      var badgeLeft = agentIconX - 14;
      var textW = Math.max(40, nameText.length * 6.5);
      var badgeRight = nameX + textW + 6;
      var badgeWidth = badgeRight - badgeLeft;
      var badgeY = p.y - 11;
      var badgeH = 22;
      var bg =
        '<rect class="topo-agent-bg" x="' +
        badgeLeft.toFixed(1) +
        '" y="' +
        badgeY.toFixed(1) +
        '" width="' +
        badgeWidth.toFixed(1) +
        '" height="' +
        badgeH +
        '" rx="11" ry="11"/>';
      /* y=p.y (same as LED cy) + dominant-baseline:middle (CSS) so
       * the glyph center aligns with the LEDs and the text baseline.
       * ywatanabe 2026-04-19: "icons must have aligned in vertical
       * axis with text and indicators". */
      /* Custom agent icon — prefer the AgentProfile-configured value
       * from cachedAgentIcons (populated by fetchAgents) so the
       * canvas node matches what the sidebar row and Agents-tab
       * card show. Cascade: image URL → emoji → 🤖 fallback. Image
       * URLs render via SVG <image>; emoji via <text>.
       * TODO.md Entity Consistency: "Icons (svg/png) must be
       * configurable with default allocations". */
      var agentGlyph = "";
      var _ai =
        typeof cachedAgentIcons !== "undefined"
          ? cachedAgentIcons[a.name] || ""
          : "";
      var _aiIsUrl =
        _ai && (_ai.indexOf("http") === 0 || _ai.indexOf("/") === 0);
      if (_aiIsUrl) {
        var _imgSize = 14;
        agentGlyph =
          '<image class="topo-agent-glyph-img" href="' +
          escapeHtml(_ai) +
          '" x="' +
          (agentIconX - _imgSize / 2).toFixed(1) +
          '" y="' +
          (p.y - _imgSize / 2).toFixed(1) +
          '" width="' +
          _imgSize +
          '" height="' +
          _imgSize +
          '" preserveAspectRatio="xMidYMid slice"/>';
      } else if (_ai) {
        /* User-assigned emoji via AgentProfile.icon_emoji. */
        agentGlyph =
          '<text class="topo-agent-glyph" x="' +
          agentIconX.toFixed(1) +
          '" y="' +
          p.y.toFixed(1) +
          '" font-size="12" dominant-baseline="central" text-anchor="middle">' +
          _ai +
          "</text>";
      } else {
        /* Default: scitex S-shaped snake SVG from the CENTRAL source
         * (getSnakeIcon in agent-icons.js). User 2026-04-20: "please
         * use central, single-source-of-icons". Wrap the returned
         * SVG in a <g translate> so it lands at the right position
         * inside the parent canvas SVG. Nested <svg> is valid and
         * establishes its own viewport from the inner viewBox. */
        var _snakeSize = 14;
        var _snakeColor =
          (_ident && _ident.color) ||
          (typeof getAgentColor === "function"
            ? getAgentColor(a.name)
            : "#4ecdc4");
        var _snakeMarkup =
          typeof getSnakeIcon === "function"
            ? getSnakeIcon(_snakeSize, _snakeColor)
            : "";
        /* getSnakeIcon returns an <svg> with its own width/height but
         * no x/y. Insert x/y via a single regex so the canvas can
         * position it without touching the source helper. */
        _snakeMarkup = _snakeMarkup.replace(
          /<svg /,
          '<svg x="' +
            (agentIconX - _snakeSize / 2).toFixed(1) +
            '" y="' +
            (p.y - _snakeSize / 2).toFixed(1) +
            '" ',
        );
        agentGlyph = _snakeMarkup;
      }
      return (
        '<g class="topo-node topo-agent' +
        selCls +
        deadCls +
        '" data-agent="' +
        escapeHtml(a.name) +
        '">' +
        /* todo#96: shared tooltip — same "<id> (<machine>)" string as
         * the sidebar agent row so hover text agrees across surfaces. */
        "<title>" +
        escapeHtml(_ident.tooltip) +
        "</title>" +
        bg +
        agentGlyph +
        wsLed +
        fnLed +
        pinMark +
        '<text class="topo-label topo-label-agent" x="' +
        nameX.toFixed(1) +
        '" y="' +
        (p.y + 4).toFixed(1) +
        '" fill="' +
        color +
        '">' +
        escapeHtml(nameText) +
        "</text>" +
        "</g>"
      );
    })
    .join("");

  return agentSvg;
}

function _topoBuildHumanSvg(humanName, agentPos) {
  /* Human node — rendered after agents so it layers on top. Gold
   * pill with a 👤 glyph prefix; wired through the same data-agent
   * hook so the packet animator's sender lookup works unchanged. */
  var humanSvg = "";
  if (humanName && agentPos[humanName]) {
    var hp = agentPos[humanName];
    var hLabel = humanName;
    var hTextW = Math.max(40, hLabel.length * 6.5);
    var hBadgeLeft = hp.x - 18;
    var hBadgeWidth = 18 + 14 + hTextW + 6;
    /* Human face glyph cascade: UserProfile icon_image (URL) renders
     * as SVG <image>; icon_emoji renders as <text>; else default 👤.
     * Uses cachedHumanIcons populated by fetchHumanProfiles in
     * agent-icons.js. User report 2026-04-20: "I setup my face icon
     * but it is not shown in the canvas". */
    var _hi =
      typeof cachedHumanIcons !== "undefined" && cachedHumanIcons[humanName]
        ? cachedHumanIcons[humanName]
        : "";
    var _hiIsUrl = _hi && (_hi.indexOf("http") === 0 || _hi.indexOf("/") === 0);
    var humanGlyph;
    if (_hiIsUrl) {
      var _imgSize = 16;
      humanGlyph =
        '<image class="topo-human-glyph topo-human-glyph-img" href="' +
        escapeHtml(_hi) +
        '" x="' +
        (hp.x - 10 - _imgSize / 2 + 7).toFixed(1) +
        '" y="' +
        (hp.y - _imgSize / 2).toFixed(1) +
        '" width="' +
        _imgSize +
        '" height="' +
        _imgSize +
        '" preserveAspectRatio="xMidYMid slice"/>';
    } else {
      var humanEmoji = _hi || "\uD83D\uDC64";
      humanGlyph =
        '<text class="topo-human-glyph" x="' +
        (hp.x - 10).toFixed(1) +
        '" y="' +
        (hp.y + 4).toFixed(1) +
        '" font-size="13">' +
        humanEmoji +
        "</text>";
    }
    humanSvg =
      '<g class="topo-node topo-agent topo-human" data-agent="' +
      escapeHtml(humanName) +
      '">' +
      '<rect class="topo-agent-bg topo-human-bg" x="' +
      hBadgeLeft.toFixed(1) +
      '" y="' +
      (hp.y - 11).toFixed(1) +
      '" width="' +
      hBadgeWidth.toFixed(1) +
      '" height="22" rx="11" ry="11"/>' +
      humanGlyph +
      '<text class="topo-label topo-label-agent" x="' +
      (hp.x + 6).toFixed(1) +
      '" y="' +
      (hp.y + 4).toFixed(1) +
      '" fill="#fbbf24">' +
      escapeHtml(hLabel) +
      "</text>" +
      "</g>";
  }

  return humanSvg;
}
