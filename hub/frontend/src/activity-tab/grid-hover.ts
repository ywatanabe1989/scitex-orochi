// @ts-nocheck
/* activity-tab/grid-hover.js — channel + agent hover highlight for
 * the topology canvas. Mouseover on a channel/agent node adds
 * .topo-edge-hover to connected edges and highlights endpoint
 * channels/agents. Helper wired from grid-delegation.js. */


function _ovgWireHover(grid) {
  /* Channel-hover → highlight every edge connected to that channel +
   * the endpoint agent nodes. Makes the network topology visually
   * discoverable: hover a channel diamond, the fleet subscribed to it
   * lights up. Uses mouseover/mouseout (bubbling) on the grid so the
   * delegation survives SVG re-renders. ywatanabe 2026-04-19: "when
   * hovered on a channel, all the lines from there should be
   * highlighted as visual feedback to show the network". */
  function _topoChannelHoverClear() {
    var hovered = grid.querySelectorAll(
      ".topo-edges line.topo-edge-hover, .topo-agent.topo-agent-connected",
    );
    for (var i = 0; i < hovered.length; i++) {
      hovered[i].classList.remove("topo-edge-hover");
      hovered[i].classList.remove("topo-agent-connected");
    }
  }
  function _topoChannelHoverApply(chName) {
    if (!chName) return;
    /* Only visible edges — skip .topo-edge-hit overlays. Adding
     * .topo-edge-hover to a transparent overlay would make the CSS
     * `stroke:#4ecdc4 !important` rule suddenly paint it cyan. */
    var edges = grid.querySelectorAll(".topo-edges line:not(.topo-edge-hit)");
    var endpoints = {};
    for (var i = 0; i < edges.length; i++) {
      var ln = edges[i];
      var lnCh = ln.getAttribute("data-channel");
      var lnDmCh = ln.getAttribute("data-dm-channel");
      if (lnCh === chName) {
        ln.classList.add("topo-edge-hover");
        var ag = ln.getAttribute("data-agent");
        if (ag) endpoints[ag] = true;
      } else if (lnDmCh === chName) {
        ln.classList.add("topo-edge-hover");
        var dmA = ln.getAttribute("data-dm-a");
        var dmB = ln.getAttribute("data-dm-b");
        if (dmA) endpoints[dmA] = true;
        if (dmB) endpoints[dmB] = true;
      }
    }
    Object.keys(endpoints).forEach(function (ep) {
      var nodes = grid.querySelectorAll(
        '.topo-agent[data-agent="' + ep.replace(/"/g, '\\"') + '"]',
      );
      for (var j = 0; j < nodes.length; j++) {
        nodes[j].classList.add("topo-agent-connected");
      }
    });
  }
  grid.addEventListener("mouseover", function (ev) {
    var chNode = ev.target.closest(".topo-channel[data-channel]");
    if (!chNode || !grid.contains(chNode)) return;
    var chName = chNode.getAttribute("data-channel");
    if (!chName) return;
    /* Skip re-apply if the cursor moves between children of the same
     * channel node (e.g. polygon → text) — mouseover fires on each. */
    if (chNode.dataset.topoHoverActive === "1") return;
    _topoChannelHoverClear();
    chNode.dataset.topoHoverActive = "1";
    _topoChannelHoverApply(chName);
  });
  grid.addEventListener("mouseout", function (ev) {
    var chNode = ev.target.closest(".topo-channel[data-channel]");
    if (!chNode || !grid.contains(chNode)) return;
    /* mouseout fires when leaving a child; only clear when the cursor
     * has actually left the whole .topo-channel group. */
    var related = ev.relatedTarget;
    if (related && chNode.contains(related)) return;
    delete chNode.dataset.topoHoverActive;
    _topoChannelHoverClear();
  });

  /* Agent-hover → highlight every edge connected to that agent + the
   * endpoint channel nodes + any DM peer agent. Mirrors the channel
   * hover above so the discoverability story is symmetric: hover a
   * channel, agents light up; hover an agent, channels light up.
   * User request 2026-04-19. */
  function _topoAgentHoverClear() {
    var hovered = grid.querySelectorAll(
      ".topo-edges line.topo-edge-hover, .topo-channel.topo-channel-connected, .topo-agent.topo-agent-connected",
    );
    for (var i = 0; i < hovered.length; i++) {
      hovered[i].classList.remove("topo-edge-hover");
      hovered[i].classList.remove("topo-channel-connected");
      hovered[i].classList.remove("topo-agent-connected");
    }
  }
  function _topoAgentHoverApply(agName) {
    if (!agName) return;
    var edges = grid.querySelectorAll(".topo-edges line:not(.topo-edge-hit)");
    var connectedChannels = {};
    var connectedAgents = {};
    for (var i = 0; i < edges.length; i++) {
      var ln = edges[i];
      var ag = ln.getAttribute("data-agent");
      var dmA = ln.getAttribute("data-dm-a");
      var dmB = ln.getAttribute("data-dm-b");
      var matched = false;
      if (ag === agName) {
        matched = true;
        var lnCh = ln.getAttribute("data-channel");
        if (lnCh) connectedChannels[lnCh] = true;
      }
      if (dmA === agName || dmB === agName) {
        matched = true;
        /* DM edges: both participants count as connected so the peer
         * agent lights up too, and the synthetic DM channel node (if
         * any) gets highlighted. */
        var lnDmCh = ln.getAttribute("data-dm-channel");
        if (lnDmCh) connectedChannels[lnDmCh] = true;
        if (dmA && dmA !== agName) connectedAgents[dmA] = true;
        if (dmB && dmB !== agName) connectedAgents[dmB] = true;
      }
      if (matched) ln.classList.add("topo-edge-hover");
    }
    Object.keys(connectedChannels).forEach(function (c) {
      var nodes = grid.querySelectorAll(
        '.topo-channel[data-channel="' + c.replace(/"/g, '\\"') + '"]',
      );
      for (var j = 0; j < nodes.length; j++) {
        nodes[j].classList.add("topo-channel-connected");
      }
    });
    Object.keys(connectedAgents).forEach(function (p) {
      var anodes = grid.querySelectorAll(
        '.topo-agent[data-agent="' + p.replace(/"/g, '\\"') + '"]',
      );
      for (var k = 0; k < anodes.length; k++) {
        anodes[k].classList.add("topo-agent-connected");
      }
    });
  }
  grid.addEventListener("mouseover", function (ev) {
    var agNode = ev.target.closest(".topo-agent[data-agent]");
    if (!agNode || !grid.contains(agNode)) return;
    var agName = agNode.getAttribute("data-agent");
    if (!agName) return;
    if (agNode.dataset.topoAgentHoverActive === "1") return;
    _topoAgentHoverClear();
    agNode.dataset.topoAgentHoverActive = "1";
    _topoAgentHoverApply(agName);
  });
  grid.addEventListener("mouseout", function (ev) {
    var agNode = ev.target.closest(".topo-agent[data-agent]");
    if (!agNode || !grid.contains(agNode)) return;
    var related = ev.relatedTarget;
    if (related && agNode.contains(related)) return;
    delete agNode.dataset.topoAgentHoverActive;
    _topoAgentHoverClear();
  });
}
