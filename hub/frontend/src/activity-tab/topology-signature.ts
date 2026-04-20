/* activity-tab/topology-signature.js — signature digest that lets
 * _renderActivityTopology short-circuit repaints when nothing
 * structurally changed. */


function _topoSignature(visible) {
  /* Digest: color-key selection + multi-select set + per-agent (name +
   * online-ness + liveness bucket + pinned + channel count).
   * _overviewColor goes in because swapping "color: host / account"
   * changes the text fill on every node — without it, the cache would
   * skip the re-render. Selected-set is included so toggling
   * multi-select triggers a repaint (adds/removes the
   * .topo-agent-selected class). Individual idle-seconds are NOT —
   * those flap every second and would cause pointless repaints. */
  var selSig = _topoSelectedNames().sort().join(",");
  var prefs = window._channelPrefs || {};
  var prefSig = Object.keys(prefs)
    .sort()
    .map(function (k) {
      var p = prefs[k] || {};
      return (
        k +
        (p.is_starred ? "*" : "") +
        (p.is_muted ? "m" : "") +
        (p.is_hidden ? "h" : "")
      );
    })
    .join(",");
  var stickySig = Object.keys(_topoStickyEdges).sort().join(",");
  var parts = [
    _overviewColor || "name",
    "sel:" + selSig,
    "prefs:" + prefSig,
    "sticky:" + stickySig,
    _topoHiddenSignature(),
    _topoManualPositionsSignature(),
  ];
  for (var i = 0; i < visible.length; i++) {
    var a = visible[i];
    var chCount = Array.isArray(a.channels) ? a.channels.length : 0;
    parts.push(
      (a.name || "") +
        ":" +
        (a.status === "offline" ? "0" : "1") +
        ":" +
        (a.liveness || a.status || "online") +
        ":" +
        (a.pinned ? "1" : "0") +
        ":" +
        chCount,
    );
  }
  return parts.join("|");
}

