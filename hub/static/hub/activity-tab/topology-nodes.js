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
      /* Single source of truth — channel-badge.js renderChannelBadgeSvg.
       * Same star/eye/mute UI + identical click behavior (via body
       * delegation) as the sidebar row and pool chip (ywatanabe
       * 2026-04-20: "ALL channel badge MUST have the SAME UI and
       * functionalities"). */
      if (typeof renderChannelBadgeSvg === "function") {
        return renderChannelBadgeSvg(
          c,
          { x: p.x, y: p.y, r: r },
          { showEye: true, showUnread: false, count: count },
        );
      }
      /* Fallback shouldn't fire once channel-badge.js is loaded;
       * kept minimal so the canvas still renders if the helper is
       * missing for any reason. */
      return "";
    })
    .join("");

  return chSvg;
}

function _topoBuildAgentsSvg(visible, agentPos) {
  /* Single source of truth — agent-badge-svg.js renderAgentBadgeSvg.
   * Same call surface (icon cascade + 2 LEDs + star slot + name label)
   * as the HTML agent-badge used by the sidebar row and pool chip, so
   * canvas ↔ sidebar ↔ pool stay in lockstep (ywatanabe 2026-04-20:
   * "ALL agent card MUST HAVE THE IDENTICAL AND SYNCHRONIZED BADGES").
   *
   * Per-node state derivations (dead / selected) happen here because
   * they depend on canvas-only inputs (_topoSelected, _secondsSinceIso);
   * the badge renderer just consumes the flags. */
  var agentSvg = visible
    .map(function (a) {
      var p = agentPos[a.name];
      var connected = (a.status || "online") !== "offline";
      /* Dead-state detection — heartbeat fresh but no tool / action
       * for >3min. Catches the classic "silent death" where the
       * sidecar keeps heartbeating but the LLM process is gone
       * (ywatanabe 2026-04-19). */
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
      return renderAgentBadgeSvg(
        a,
        { x: p.x, y: p.y, r: 12 },
        {
          isDead: isDead,
          isSelected: !!_topoSelected[a.name],
          iconSize: 14,
        },
      );
    })
    .join("");

  return agentSvg;
}

function _topoBuildHumanSvg(humanName, agentPos) {
  /* Human node — rendered after agents so it layers on top. Gold
   * pill with a 👤 glyph prefix; wired through the same data-agent
   * hook so the packet animator's sender lookup works unchanged.
   * Uses renderAgentBadgeSvg with isHuman:true — same SSoT as regular
   * agent nodes (2026-04-20 agent-badge-svg SSoT pass). */
  var humanSvg = "";
  if (humanName && agentPos[humanName]) {
    var hp = agentPos[humanName];
    humanSvg = renderAgentBadgeSvg(
      { name: humanName },
      { x: hp.x, y: hp.y, r: 12 },
      {
        isHuman: true,
        showLeds: false,
        iconSize: 16,
        labelOverride: humanName,
      },
    );
  }

  return humanSvg;
}
