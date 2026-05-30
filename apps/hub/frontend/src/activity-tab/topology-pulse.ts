// @ts-nocheck
import { _topoSeekUpdateUI } from "./seekbar";
import { TOPO_SEEK_WINDOW_MS, _topoSeekEvents } from "./state";
import { _topoSpawnPacket } from "./topology-packets";
import { userName } from "../app/utils";

/* activity-tab/topology-pulse.js — message-pass animation entry
 * point. Records events into the seek buffer, routes DMs via virtual-
 * midpoint single-leg flights, otherwise fires the classic two-leg
 * sender→channel→subscribers animation. */


/* Message-pass animation:
 *   leg 1 (0-900ms):   sender-agent → channel-node
 *   leg 2 (900-1800ms): channel-node → each other subscribed agent
 * So a post visibly propagates through the graph in two stages, the
 * way real pub/sub traffic would. If msg carries attachments, the
 * packet variant "topo-packet-artifact" is used (styled differently
 * as a babble bubble). ywatanabe 2026-04-19. */
export function _topoPulseEdge(sender, channel, opts) {
  /* Diagnostic tap — logs every bail-out with the relevant inputs so we
   * can see in DevTools console exactly why an expected pulse didn't
   * fire (most common: sender/recipient not in (globalThis as any)._topoLastPositions, or
   * topology tab not visible). Set window.__topoPulseDebug = false to
   * silence. ywatanabe 2026-04-19: "DM does not work in visual
   * feedback. why???". */
  var _dbg = window.__topoPulseDebug !== false;
  if (!channel) {
    if (_dbg)
      console.warn("[topo-pulse] bail: no channel", { sender, channel });
    return;
  }
  /* todo#67 — Record this pulse into the seek buffer BEFORE deciding
   * whether to live-spawn it. Replays triggered by the seekbar itself
   * set (globalThis as any)._topoSeekReplayInProgress so they don't double-record. The
   * buffer is trimmed to the last TOPO_SEEK_WINDOW_MS. */
  if (!(globalThis as any)._topoSeekReplayInProgress) {
    var _now = Date.now();
    _topoSeekEvents.push({
      ts: _now,
      sender: sender || "",
      channel: channel,
      opts: opts
        ? { isArtifact: !!opts.isArtifact, text: opts.text || "" }
        : {},
    });
    var _cutoff = _now - TOPO_SEEK_WINDOW_MS;
    while (_topoSeekEvents.length && _topoSeekEvents[0].ts < _cutoff) {
      _topoSeekEvents.shift();
    }
    /* Refresh the seekbar readout so the timestamp label and slider
     * range stretch to include the new event, but only when parked in
     * live mode (otherwise we'd tug the user's playhead). */
    if ((globalThis as any)._topoSeekMode === "live") {
      _topoSeekUpdateUI();
    }
  }
  /* While scrubbing / playing back, suppress live pulses so the
   * historical view stays stable. Replays call through here too but
   * set (globalThis as any)._topoSeekReplayInProgress=true to allow the spawn. */
  if ((globalThis as any)._topoSeekMode === "playback" && !(globalThis as any)._topoSeekReplayInProgress) {
    return;
  }
  var svg = document.querySelector(".activity-view-topology .topo-svg");
  if (!svg) {
    if (_dbg)
      console.warn("[topo-pulse] bail: topology svg not in DOM (tab hidden?)", {
        sender,
        channel,
      });
    return;
  }
  var edges = svg.querySelector(".topo-edges");
  if (!edges) {
    if (_dbg)
      console.warn("[topo-pulse] bail: .topo-edges not found", {
        sender,
        channel,
      });
    return;
  }
  var klass =
    opts && opts.isArtifact ? "topo-packet-artifact" : "topo-packet-message";
  /* Babble text that rides each packet. Caller passes the message
   * preview via opts.text (or opts.babble). Attachment-only posts
   * pass "📎" from app.js. */
  var babble = "";
  if (opts) {
    babble = opts.text || opts.babble || "";
  }
  var packetOpts = { text: babble };
  /* 0.5 second per leg — balance between legibility and not blocking
   * rapid multi-message bursts (ywatanabe 2026-04-19: "0.5s / edge
   * would be good in balance"). */
  var LEG = 500;
  /* DM branch — DMs flow along real visible edges (drawn in
   * _renderActivityTopology as <line class="topo-edge topo-edge-dm">).
   * For each recipient present on the graph, fire ONE single-leg
   * packet from sender to recipient along that edge. No virtual
   * midpoint, no tricks. ywatanabe 2026-04-19: "connect user and
   * target with a visible LINE and propagate packet along it".
   * Channel formats:
   *   dm:<principal>|<principal>...  → each "agent:<n>" or "human:<n>"
   *   dm:group:<csv names>           → comma-separated raw names
   */
  if (channel.indexOf("dm:") === 0) {
    var dmRecipients = [];
    if (channel.indexOf("dm:group:") === 0) {
      dmRecipients = channel.slice("dm:group:".length).split(",");
    } else {
      channel
        .slice("dm:".length)
        .split("|")
        .forEach(function (part) {
          if (!part) return;
          if (part.indexOf("agent:") === 0) dmRecipients.push(part.slice(6));
          else if (part.indexOf("human:") === 0)
            dmRecipients.push(part.slice(6));
          else dmRecipients.push(part);
        });
    }
    var dmFrom = sender ? (globalThis as any)._topoLastPositions.agents[sender] : null;
    if (_dbg) {
      var _sCoord = dmFrom
        ? "x:" + dmFrom.x.toFixed(1) + " y:" + dmFrom.y.toFixed(1)
        : "(not on graph)";
      console.log("coordinate sender: " + _sCoord);
    }
    if (!dmRecipients.length) {
      if (_dbg)
        console.warn("[topo-pulse] DM bail: parsed zero recipients", {
          channel,
        });
      return;
    }
    if (!dmFrom) {
      if (_dbg)
        console.warn(
          "[topo-pulse] DM bail: sender not on graph. available keys:",
          Object.keys((globalThis as any)._topoLastPositions.agents),
        );
      return;
    }
    dmRecipients.forEach(function (rn) {
      if (!rn || rn === sender) return;
      var rp = (globalThis as any)._topoLastPositions.agents[rn];
      if (_dbg) {
        console.log("DM sent from " + sender + " to " + rn);
        var _rCoord = rp
          ? "x:" + rp.x.toFixed(1) + " y:" + rp.y.toFixed(1)
          : "(not on graph)";
        console.log("coordinate receiver " + _rCoord);
      }
      if (!rp) {
        if (_dbg)
          console.warn("[topo-pulse] DM bail: recipient not on graph", {
            recipient: rn,
            channel,
            availableKeys: Object.keys((globalThis as any)._topoLastPositions.agents),
          });
        return;
      }
      /* Single-leg flight along the real DM edge. */
      _topoSpawnPacket(edges, dmFrom, rp, LEG, 0, klass, { text: babble });
    });
    return;
  }
  var cp = (globalThis as any)._topoLastPositions.channels[channel];
  if (!cp) return;
  /* Leg 1 — sender → channel IF the sender is a visible agent. Human
   * posts (sender = username, not an agent name) skip leg 1 and start
   * from the channel node — so the user still sees their post
   * propagate via leg 2 ("double-click channel → post" case). */
  var ap = sender ? (globalThis as any)._topoLastPositions.agents[sender] : null;
  var leg2Delay = 0;
  if (ap) {
    _topoSpawnPacket(edges, ap, cp, LEG, 0, klass, packetOpts);
    leg2Delay = LEG;
  } else {
    /* Brief in-place pulse on the channel so the origin is visible
     * before the fan-out leg. */
    _topoSpawnPacket(edges, cp, cp, 180, 0, klass, packetOpts);
  }
  /* Leg 2 — channel → every other connected node (subscribed agents
   * AND the human user). The human is in (globalThis as any)._topoLastPositions.agents
   * keyed by username but is NOT present in window.__lastAgents, so
   * the filter has two paths: an agent record with the channel in
   * its a.channels OR the human node (always treated as reachable,
   * since the dashed edges imply full connectivity). Sender is
   * excluded so replies don't bounce back to the poster. ywatanabe
   * 2026-04-19: "from the channel node, it should be sent to user
   * as well (or other connected nodes than the sender itself)". */
  var humanKey =
    (typeof userName !== "undefined" && userName) ||
    window.__orochiUserName ||
    "";
  var subscribers = Object.keys((globalThis as any)._topoLastPositions.agents).filter(function (n) {
    if (n === sender) return false;
    if (humanKey && n === humanKey) return true;
    var ag = (window.__lastAgents || []).find(function (x) {
      return x.name === n;
    });
    return (
      ag && Array.isArray(ag.channels) && ag.channels.indexOf(channel) !== -1
    );
  });
  subscribers.forEach(function (n) {
    var target = (globalThis as any)._topoLastPositions.agents[n];
    if (!target) return;
    _topoSpawnPacket(edges, cp, target, LEG, leg2Delay, klass, packetOpts);
  });
}
window._topoPulseEdge = _topoPulseEdge;

