// @ts-nocheck
import { _permKey } from "./data";

/* activity-tab/topology-arrows.js — permission-direction arrow
 * markers on topology edges. */

/* Map a permission string to the SVG attribute fragment that places
 * arrows on the correct endpoint(s). Each line is drawn agent→channel
 * (x1/y1 = agent, x2/y2 = channel), so marker-start sits at the agent
 * and marker-end sits at the channel.
 *   read-only   (agent reads from channel)  → arrow at agent end
 *   read-write  (bidirectional)              → arrows on both ends
 *   write-only  (agent writes to channel)    → arrow at channel end
 */
export function _markerAttrsForPerm(perm) {
  if (perm === "read-only") {
    return ' marker-start="url(#topo-arrow-start)"';
  }
  if (perm === "write-only") {
    return ' marker-end="url(#topo-arrow-end)"';
  }
  /* default = read-write → both */
  return ' marker-start="url(#topo-arrow-start)" marker-end="url(#topo-arrow-end)"';
}

/* After a permission-fetch resolves we only need to update the
 * `marker-start`/`marker-end` attributes on existing <line> elements,
 * NOT rebuild the SVG (that would thrash zoom state). */
export function _repaintTopoArrows() {
  var svg = document.querySelector(".activity-view-topology .topo-svg");
  if (!svg) return;
  /* Only visible edges carry marker-start/marker-end; the .topo-edge-hit
   * overlays are transparent and should not accumulate marker attrs. */
  var lines = svg.querySelectorAll(
    ".topo-edges line.topo-edge[data-agent][data-channel]",
  );
  for (var i = 0; i < lines.length; i++) {
    var ln = lines[i];
    var name = ln.getAttribute("data-agent");
    var ch = ln.getAttribute("data-channel");
    var perm = (globalThis as any)._topoChannelPerms[_permKey(ch, name)] || "read-write";
    if (perm === "read-only") {
      ln.setAttribute("marker-start", "url(#topo-arrow-start)");
      ln.removeAttribute("marker-end");
    } else if (perm === "write-only") {
      ln.removeAttribute("marker-start");
      ln.setAttribute("marker-end", "url(#topo-arrow-end)");
    } else {
      ln.setAttribute("marker-start", "url(#topo-arrow-start)");
      ln.setAttribute("marker-end", "url(#topo-arrow-end)");
    }
  }
}

