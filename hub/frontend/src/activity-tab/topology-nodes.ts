// @ts-nocheck
import { _topoSelected } from "./multiselect";
import { _secondsSinceIso } from "./utils";
import { renderAgentBadgeSvg } from "../agent-badge-svg";
import { renderChannelBadgeSvg } from "../channel-badge";

/* activity-tab/topology-nodes.js — SVG emission for channel nodes,
 * agent pills, and the human user node.
 *
 * PR #<this> Item 9 (ywatanabe msg#15637): channel nodes are rendered
 * ONLY through renderChannelBadgeSvg — the prior rotated-square
 * "diamond" shape is removed. Every node (agent AND channel) now
 * goes through the shared badge modules so canvas ↔ sidebar ↔ pool
 * stay in lockstep ("channel ノードの ダイヤモンド形状は削除、
 * identity badge だけで十分"). No parallel renderer; no diamond
 * fallback. */

export function _topoBuildChannelsSvg(
  visible,
  channels,
  chPos,
  chSet,
  _chPrefs,
) {
  /* Per-channel subscriber counts across the visible agents. Used to
   * scale each channel badge — "based on the number of agents, the
   * channel node can be larger" (ywatanabe 2026-04-19). */
  var chAgentCounts = {};
  visible.forEach(function (a) {
    (a.channels || []).forEach(function (c) {
      if (!chSet[c]) return;
      chAgentCounts[c] = (chAgentCounts[c] || 0) + 1;
    });
  });
  /* Channel badges (horizontal pills via renderChannelBadgeSvg) with
   * identity inline. Size scales per user-selected "size:" dropdown
   * (todo#95):
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
      if ((globalThis as any)._topoSizeBy === "subscribers") {
        r = Math.min(22, 8 + Math.sqrt(Math.max(0, count - 1)) * 5);
      } else {
        /* equal + posts (deferred) */
        r = 12;
      }
      /* Single source of truth — channel-badge.js renderChannelBadgeSvg.
       * Canonical element order: icon + star + eye + mute + name,
       * IDENTICAL to the HTML renderer used by the sidebar row and
       * pool chip, so all three sites (sidebar / pool / canvas) read
       * left-to-right the same way and carry the same star/eye/mute
       * UI + click behavior via body-level delegation (ywatanabe
       * 2026-04-20: "ALL channel badge MUST have the SAME UI and
       * functionalities"). No inline glyph/star/eye/mute emission
       * here — the SSoT owns the full channel visual. */
      /* Item 9: no fallback — renderChannelBadgeSvg is the ONLY path.
       * channel-badge.ts loads before this file in the Vite bundle
       * (see src/index.ts import order), so the helper is always
       * defined. If it is missing we want to fail loudly rather than
       * silently render nothing. */
      return renderChannelBadgeSvg(
        c,
        { x: p.x, y: p.y, r: r },
        { showEye: true, showUnread: false, count: count },
      );
    })
    .join("");

  return chSvg;
}

export function _topoBuildAgentsSvg(visible, agentPos) {
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
      /* Dead-state detection — defers to the agent_meta classifier's
       * `pane_state` field (`stale` = 3+ cycles unchanged with no busy
       * markers AND not at an empty `❯ ` idle prompt). Falls back to
       * the legacy 180s tool/action timer when pane_state is missing
       * (e.g. agent_meta.py not deployed on a host). Single source of
       * truth: same logic as `_isDeadAgent` in ./utils.ts. */
      var pane = (a.pane_state || "").toLowerCase();
      var isDead;
      if (pane === "stale") {
        isDead = connected;
      } else if (pane) {
        isDead = false;
      } else {
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
        isDead = connected && noTool && noAct;
      }
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

export function _topoBuildHumanSvg(humanName, agentPos) {
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
