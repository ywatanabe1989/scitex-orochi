// @ts-nocheck
// Migrated classic-script file. Types intentionally loose during
// the big-bang JS-to-TS bundle migration. Narrow later, per-file.
/* activity-tab/topology-packets.js — packet animation on topology
 * edges: spawnPacket with rAF flight, landing bubble at destination,
 * flashEdge for brief endpoint highlight. */

/* Spawn one glowing packet traveling from (fromX,fromY) -> (toX,toY)
 * over `dur` ms, optionally delayed. Self-removes after animation. */
/* Modern directional packet. Three-layer glow (outer halo + mid ring
 * + bright core) rotated to face the direction of travel so the
 * whole shape reads as a capsule pointing downstream. Flying a few
 * of these in quick succession gives a "data bus" feel (buzz factor
 * per ywatanabe 2026-04-19). Self-removes ~80ms after animation. */
function _topoSpawnPacket(edges, from, to, dur, delay, klass, opts) {
  var ns = "http://www.w3.org/2000/svg";
  var dx = to.x - from.x;
  var dy = to.y - from.y;
  var inPlace = Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5;
  /* Pure JS requestAnimationFrame animation — SMIL was unreliable in
   * practice (the packets "glowed in place" without visibly moving).
   * rAF gives us a guaranteed per-frame setAttribute on cx/cy, plus
   * easy fade-out control. ywatanabe 2026-04-19: "from start to end,
   * use 1 sec". */
  var g = document.createElementNS(ns, "g");
  g.setAttribute("class", "topo-packet " + (klass || ""));
  var halo, core, burst;
  if (inPlace) {
    burst = document.createElementNS(ns, "circle");
    burst.setAttribute("cx", String(from.x));
    burst.setAttribute("cy", String(from.y));
    burst.setAttribute("r", "4");
    burst.setAttribute("fill-opacity", "0.55");
    g.appendChild(burst);
  } else {
    halo = document.createElementNS(ns, "circle");
    halo.setAttribute("cx", String(from.x));
    halo.setAttribute("cy", String(from.y));
    halo.setAttribute("r", "16");
    halo.setAttribute("fill-opacity", "0.2");
    g.appendChild(halo);
    core = document.createElementNS(ns, "circle");
    core.setAttribute("cx", String(from.x));
    core.setAttribute("cy", String(from.y));
    core.setAttribute("r", "7");
    core.setAttribute("fill-opacity", "0.95");
    g.appendChild(core);
  }
  /* Babble — a small speech-bubble that follows the packet showing the
   * first ~60 chars of the message text (or "📎" for attachment-only
   * packets). Fades out in sync with the packet. Built as an SVG
   * <rect>+<text> pair so it translates naturally with cx/cy updates
   * and stays inside the topology <svg>'s coord system. SVG <text>
   * has no native background, hence the <rect> drawn first. */
  /* Message preview (babble) is NOT shown during flight — only lands
   * at the destination via `_topoLandingBubble(to, text)` when t>=1.
   * ywatanabe 2026-04-19 "do not show packet message until reached
   * to destination" / "only show message after reaching destination".
   * We just normalize + truncate the text here so the landing bubble
   * receives a ready-to-render string. */
  var babbleText = opts && opts.text ? String(opts.text) : "";
  babbleText = babbleText.replace(/\s+/g, " ").trim();
  if (babbleText.length > 60) babbleText = babbleText.slice(0, 60) + "\u2026";
  edges.appendChild(g);

  var startTime = null;
  function _frame(ts) {
    if (!g.parentNode) return; /* removed externally */
    if (startTime == null) startTime = ts;
    var elapsed = ts - startTime - delay;
    if (elapsed < 0) {
      requestAnimationFrame(_frame);
      return;
    }
    var t = Math.min(1, elapsed / dur);
    var curX = from.x;
    var curY = from.y;
    if (inPlace) {
      /* Expanding fading ring. */
      burst.setAttribute("r", String(4 + (20 - 4) * t));
      burst.setAttribute("fill-opacity", String(0.55 * (1 - t)));
    } else {
      curX = from.x + dx * t;
      curY = from.y + dy * t;
      halo.setAttribute("cx", String(curX));
      halo.setAttribute("cy", String(curY));
      core.setAttribute("cx", String(curX));
      core.setAttribute("cy", String(curY));
      /* Breathing pulse — subtle size modulation while in flight so the
       * packet reads as a live/organic thing, not a rigid dot. Two
       * breaths per traversal, halo ±22%, core ±15%. ywatanabe
       * 2026-04-19: "add animation, to the packet; a bit changing size
       * like breezing". */
      var breath = Math.sin(t * Math.PI * 4);
      halo.setAttribute("r", String(16 * (1 + 0.22 * breath)));
      core.setAttribute("r", String(7 * (1 + 0.15 * breath)));
      /* Fade out in the last 20% so the packet evaporates into the
       * destination node instead of hard-landing with lingering glow. */
      if (t > 0.8) {
        var fade = 1 - (t - 0.8) / 0.2;
        halo.setAttribute("fill-opacity", String(0.2 * fade));
        core.setAttribute("fill-opacity", String(0.95 * fade));
      }
    }
    /* No in-flight babble — message text only renders at destination
     * via the landing bubble below. */
    if (t < 1) {
      requestAnimationFrame(_frame);
    } else {
      /* Landing bubble — show the message text as a speech bubble
       * attached to the destination node (stacks with concurrent
       * arrivals, fades in/out over 1s). Skipped for inPlace packets
       * (those are already at the origin) and when there's no text. */
      if (!inPlace && babbleText) {
        try {
          var svgRoot = edges && edges.ownerSVGElement;
          if (svgRoot) _topoLandingBubble(svgRoot, to, babbleText);
        } catch (_) {
          /* non-fatal */
        }
      }
      /* Remove shortly after landing so no lingering glow remains. */
      setTimeout(function () {
        if (g.parentNode) g.parentNode.removeChild(g);
      }, 20);
    }
  }
  requestAnimationFrame(_frame);
  /* Safety removal in case the tab is backgrounded and rAF stalls. */
  setTimeout(
    function () {
      if (g.parentNode) g.parentNode.removeChild(g);
    },
    dur + delay + 500,
  );
}

/* Landing bubble — a short-lived speech bubble ATTACHED to the
 * destination node when a packet arrives. Separate from the in-flight
 * babble that rides the packet. Multiple arrivals at the same node
 * stack vertically (newest at bottom, older bubbles lift ~18px up).
 * Fade driven by CSS (@keyframes topo-landing-fade 1s ease-out);
 * lifecycle (stack cleanup) driven by JS setTimeout.
 * ywatanabe 2026-04-19: "after reaching to the target, as a bubble,
 * the message should be shown and stacked and disappeared with timer
 * like 1 s duration" / "and as bubble on the destination". */
function _topoLandingBubble(svgRoot, target, text) {
  if (!svgRoot || !target || text == null) return;
  var txt = String(text).replace(/\s+/g, " ").trim();
  if (!txt) return;
  if (txt.length > 60) txt = txt.slice(0, 60) + "\u2026";
  /* Prefer a dedicated .topo-landings layer so bubbles render above
   * edges/nodes. Create it lazily (render() doesn't know we exist). */
  var layer = svgRoot.querySelector(".topo-landings");
  if (!layer) {
    layer = document.createElementNS("http://www.w3.org/2000/svg", "g");
    layer.setAttribute("class", "topo-landings");
    svgRoot.appendChild(layer);
  }
  var ns = "http://www.w3.org/2000/svg";
  var key = Math.round(target.x) + "," + Math.round(target.y);
  var stack = _topoLandingStacks[key];
  if (!stack) {
    stack = [];
    _topoLandingStacks[key] = stack;
  }
  /* Cap stack — drop oldest (index 0) if we'd exceed the cap. */
  while (stack.length >= _TOPO_LANDING_STACK_MAX) {
    var dropped = stack.shift();
    if (dropped) {
      if (dropped.timer) clearTimeout(dropped.timer);
      if (dropped.g && dropped.g.parentNode) {
        dropped.g.parentNode.removeChild(dropped.g);
      }
    }
  }
  /* Two-level group so CSS transform-driven fade (translateY) composes
   * with our JS-driven stack position (translate(x,y)) without one
   * overwriting the other. Outer <g> = position attribute; inner
   * <g class="topo-landing"> = CSS keyframe animation. */
  var g = document.createElementNS(ns, "g");
  var inner = document.createElementNS(ns, "g");
  inner.setAttribute("class", "topo-landing");
  var label = document.createElementNS(ns, "text");
  label.setAttribute("class", "topo-landing-text");
  label.setAttribute("text-anchor", "middle");
  label.setAttribute("dominant-baseline", "middle");
  label.textContent = txt;
  var rect = document.createElementNS(ns, "rect");
  rect.setAttribute("class", "topo-landing-bg");
  rect.setAttribute("rx", "4");
  rect.setAttribute("ry", "4");
  inner.appendChild(rect);
  inner.appendChild(label);
  g.appendChild(inner);
  layer.appendChild(g);
  /* Position — newest bubble sits closest to the node (offset 0);
   * older entries (already in stack) get pushed up one step each. */
  function _placeStack() {
    for (var i = 0; i < stack.length; i++) {
      var entry = stack[i];
      if (!entry || !entry.g) continue;
      /* Index (stack.length - 1 - i) counted from newest: 0 = closest. */
      var posFromBottom = stack.length - 1 - i;
      var dy = -24 - posFromBottom * _TOPO_LANDING_STEP_PX;
      entry.g.setAttribute(
        "transform",
        "translate(" + target.x + "," + (target.y + dy) + ")",
      );
    }
  }
  var entry = {
    g: g,
    timer: null,
    expireAt: Date.now() + _TOPO_LANDING_DUR_MS,
  };
  stack.push(entry);
  /* Need the text in the DOM first so getBBox works; then size the rect. */
  try {
    var bbox = label.getBBox();
    var padX = 6;
    var padY = 2;
    rect.setAttribute("x", String(bbox.x - padX));
    rect.setAttribute("y", String(bbox.y - padY));
    rect.setAttribute("width", String(bbox.width + padX * 2));
    rect.setAttribute("height", String(bbox.height + padY * 2));
  } catch (_) {
    /* bbox may fail if tab is hidden — harmless, bubble will still animate. */
  }
  _placeStack();
  entry.timer = setTimeout(function () {
    /* Remove from stack + DOM. Then re-place remaining so they drop
     * back toward the node as older ones expire. */
    var idx = stack.indexOf(entry);
    if (idx >= 0) stack.splice(idx, 1);
    if (g.parentNode) g.parentNode.removeChild(g);
    if (stack.length === 0) {
      delete _topoLandingStacks[key];
    } else {
      _placeStack();
    }
  }, _TOPO_LANDING_DUR_MS);
}

/* Briefly brighten the line matching the given endpoints. Skip the
 * invisible .topo-edge-hit overlays — adding .topo-edge-live there
 * would suddenly make the transparent hit strip flash cyan. */
function _topoFlashEdge(edges, a, b, delay, dur) {
  var lines = edges.querySelectorAll("line:not(.topo-edge-hit)");
  for (var i = 0; i < lines.length; i++) {
    var ln = lines[i];
    var x1 = Number(ln.getAttribute("x1"));
    var y1 = Number(ln.getAttribute("y1"));
    var x2 = Number(ln.getAttribute("x2"));
    var y2 = Number(ln.getAttribute("y2"));
    var matchA =
      Math.abs(x1 - a.x) < 0.5 &&
      Math.abs(y1 - a.y) < 0.5 &&
      Math.abs(x2 - b.x) < 0.5 &&
      Math.abs(y2 - b.y) < 0.5;
    var matchB =
      Math.abs(x1 - b.x) < 0.5 &&
      Math.abs(y1 - b.y) < 0.5 &&
      Math.abs(x2 - a.x) < 0.5 &&
      Math.abs(y2 - a.y) < 0.5;
    if (matchA || matchB) {
      (function (line) {
        setTimeout(function () {
          line.classList.add("topo-edge-live");
          setTimeout(function () {
            line.classList.remove("topo-edge-live");
          }, dur);
        }, delay);
      })(ln);
      break;
    }
  }
}

