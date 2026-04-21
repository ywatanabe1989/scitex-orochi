/* activity-tab/zoompan.js — drag-rectangle zoom + shift-drag pan
 * + ctrl-drag lasso + wheel zoom/pan + keyboard shortcuts +
 * zoom button controls for the topology SVG. */


/* Drag-rectangle zoom + shift-drag pan + double-click reset on the
 * topology SVG. State lives in _topoViewBox so heartbeat-driven
 * re-renders preserve the zoom. The inner .topo-zoombox <rect> is
 * reused as the drag overlay. Bound ONCE — the inner SVG is replaced
 * on each render but the grid wrapper is stable. */
function _wireTopoZoomPan(grid, W, H) {
  if (_topoZoomWired || !grid) return;
  _topoZoomWired = true;
  function _svgPoint(svg, clientX, clientY) {
    var pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    var m = svg.getScreenCTM();
    if (!m) return { x: clientX, y: clientY };
    var inv = m.inverse();
    var p = pt.matrixTransform(inv);
    return { x: p.x, y: p.y };
  }
  function _pushVB() {
    if (_topoViewBox)
      _topoViewBoxHistory.push({
        x: _topoViewBox.x,
        y: _topoViewBox.y,
        w: _topoViewBox.w,
        h: _topoViewBox.h,
      });
    else _topoViewBoxHistory.push(null);
    if (_topoViewBoxHistory.length > 30) _topoViewBoxHistory.shift();
    /* Any new zoom/pan invalidates the redo chain — matches browser
     * history semantics. */
    _topoViewBoxFuture.length = 0;
  }
  function _applyVB(svg, vb) {
    if (!vb) svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    else
      svg.setAttribute(
        "viewBox",
        vb.x.toFixed(1) +
          " " +
          vb.y.toFixed(1) +
          " " +
          vb.w.toFixed(1) +
          " " +
          vb.h.toFixed(1),
      );
  }
  function _zoomAt(svg, factor, cx, cy) {
    var vb = _topoViewBox || { x: 0, y: 0, w: W, h: H };
    if (cx == null) cx = vb.x + vb.w / 2;
    if (cy == null) cy = vb.y + vb.h / 2;
    var nw = vb.w * factor;
    var nh = vb.h * factor;
    var nx = cx - (cx - vb.x) * factor;
    var ny = cy - (cy - vb.y) * factor;
    _pushVB();
    _topoViewBox = { x: nx, y: ny, w: nw, h: nh };
    _applyVB(svg, _topoViewBox);
  }
  function _popVB(svg) {
    if (!_topoViewBoxHistory.length) return;
    /* Save current state onto the future stack so Forward can redo. */
    _topoViewBoxFuture.push(
      _topoViewBox
        ? {
            x: _topoViewBox.x,
            y: _topoViewBox.y,
            w: _topoViewBox.w,
            h: _topoViewBox.h,
          }
        : null,
    );
    var prev = _topoViewBoxHistory.pop();
    _topoViewBox = prev;
    _applyVB(svg, prev);
  }
  function _forwardVB(svg) {
    if (!_topoViewBoxFuture.length) return;
    _topoViewBoxHistory.push(
      _topoViewBox
        ? {
            x: _topoViewBox.x,
            y: _topoViewBox.y,
            w: _topoViewBox.w,
            h: _topoViewBox.h,
          }
        : null,
    );
    var next = _topoViewBoxFuture.pop();
    _topoViewBox = next;
    _applyVB(svg, next);
  }
  function _resetVB(svg) {
    _pushVB();
    _topoViewBox = null;
    _applyVB(svg, null);
  }
  /* Expose for button handlers below */
  grid._topoZoomAt = _zoomAt;
  grid._topoPopVB = _popVB;
  grid._topoResetVB = _resetVB;

  var dragging = null; /* {mode:"zoom"|"pan"|"lasso", ...} */
  grid.addEventListener("mousedown", function (ev) {
    var svg = ev.target.closest && ev.target.closest(".topo-svg");
    if (!svg) return;
    if (ev.target.closest(".topo-agent, .topo-channel")) return;
    if (ev.button !== 0) return;
    ev.preventDefault();
    var start = _svgPoint(svg, ev.clientX, ev.clientY);
    /* Semantic:
     *   plain drag     = rectangle zoom
     *   shift/meta drag = pan
     *   ctrl drag       = lasso multi-select (new — ywatanabe
     *                     2026-04-19, todo#multiselect)
     * Cursor class toggles so it's default when just hovering and
     * becomes crosshair / grab / copy only during the actual drag. */
    var panMode = ev.shiftKey || ev.metaKey;
    var lassoMode = ev.ctrlKey && !panMode;
    if (lassoMode) {
      dragging = {
        mode: "lasso",
        svg: svg,
        startSvg: start,
        endSvg: start,
        additive: true,
      };
      var lrect = svg.querySelector(".topo-lasso");
      if (lrect) {
        lrect.setAttribute("x", String(start.x));
        lrect.setAttribute("y", String(start.y));
        lrect.setAttribute("width", "0");
        lrect.setAttribute("height", "0");
        lrect.style.display = "";
      }
      svg.classList.add("topo-lassoing");
    } else if (panMode) {
      var vb = _topoViewBox || { x: 0, y: 0, w: W, h: H };
      dragging = {
        mode: "pan",
        svg: svg,
        startX: ev.clientX,
        startY: ev.clientY,
        startVB: { x: vb.x, y: vb.y, w: vb.w, h: vb.h },
      };
      svg.classList.add("topo-panning");
    } else {
      dragging = {
        mode: "zoom",
        svg: svg,
        startSvg: start,
        endSvg: start,
      };
      var rect = svg.querySelector(".topo-zoombox");
      if (rect) {
        rect.setAttribute("x", String(start.x));
        rect.setAttribute("y", String(start.y));
        rect.setAttribute("width", "0");
        rect.setAttribute("height", "0");
        rect.style.display = "";
      }
      svg.classList.add("topo-zooming");
    }
  });
  grid.addEventListener("mousemove", function (ev) {
    if (!dragging) return;
    if (dragging.mode === "zoom") {
      var p = _svgPoint(dragging.svg, ev.clientX, ev.clientY);
      dragging.endSvg = p;
      var rect = dragging.svg.querySelector(".topo-zoombox");
      if (rect) {
        var x = Math.min(dragging.startSvg.x, p.x);
        var y = Math.min(dragging.startSvg.y, p.y);
        var w = Math.abs(p.x - dragging.startSvg.x);
        var h = Math.abs(p.y - dragging.startSvg.y);
        rect.setAttribute("x", x.toFixed(1));
        rect.setAttribute("y", y.toFixed(1));
        rect.setAttribute("width", w.toFixed(1));
        rect.setAttribute("height", h.toFixed(1));
      }
    } else if (dragging.mode === "lasso") {
      var pL = _svgPoint(dragging.svg, ev.clientX, ev.clientY);
      dragging.endSvg = pL;
      var lrect = dragging.svg.querySelector(".topo-lasso");
      if (lrect) {
        var lx = Math.min(dragging.startSvg.x, pL.x);
        var ly = Math.min(dragging.startSvg.y, pL.y);
        var lw = Math.abs(pL.x - dragging.startSvg.x);
        var lh = Math.abs(pL.y - dragging.startSvg.y);
        lrect.setAttribute("x", lx.toFixed(1));
        lrect.setAttribute("y", ly.toFixed(1));
        lrect.setAttribute("width", lw.toFixed(1));
        lrect.setAttribute("height", lh.toFixed(1));
      }
    } else if (dragging.mode === "pan") {
      /* Translate clientX/Y delta to SVG coordinates via the viewBox
       * aspect ratio. Simpler: work in screen px scaled by current
       * viewBox/screen ratio. */
      var dxScreen = ev.clientX - dragging.startX;
      var dyScreen = ev.clientY - dragging.startY;
      var svgW = dragging.svg.clientWidth || W;
      var svgH = dragging.svg.clientHeight || H;
      var sx = dragging.startVB.w / svgW;
      var sy = dragging.startVB.h / svgH;
      var nx = dragging.startVB.x - dxScreen * sx;
      var ny = dragging.startVB.y - dyScreen * sy;
      _topoViewBox = {
        x: nx,
        y: ny,
        w: dragging.startVB.w,
        h: dragging.startVB.h,
      };
      dragging.svg.setAttribute(
        "viewBox",
        _topoViewBox.x.toFixed(1) +
          " " +
          _topoViewBox.y.toFixed(1) +
          " " +
          _topoViewBox.w.toFixed(1) +
          " " +
          _topoViewBox.h.toFixed(1),
      );
    }
  });
  grid.addEventListener("mouseup", function (ev) {
    if (!dragging) return;
    var svg = dragging.svg;
    if (dragging.mode === "zoom") {
      var p = _svgPoint(svg, ev.clientX, ev.clientY);
      var x = Math.min(dragging.startSvg.x, p.x);
      var y = Math.min(dragging.startSvg.y, p.y);
      var w = Math.abs(p.x - dragging.startSvg.x);
      var h = Math.abs(p.y - dragging.startSvg.y);
      if (w > 8 && h > 8) {
        _pushVB();
        _topoViewBox = { x: x, y: y, w: w, h: h };
        _applyVB(svg, _topoViewBox);
      }
      var rect = svg.querySelector(".topo-zoombox");
      if (rect) rect.style.display = "none";
    } else if (dragging.mode === "lasso") {
      var pL = _svgPoint(svg, ev.clientX, ev.clientY);
      var lx = Math.min(dragging.startSvg.x, pL.x);
      var ly = Math.min(dragging.startSvg.y, pL.y);
      var lw = Math.abs(pL.x - dragging.startSvg.x);
      var lh = Math.abs(pL.y - dragging.startSvg.y);
      var lrect = svg.querySelector(".topo-lasso");
      if (lrect) lrect.style.display = "none";
      /* Select every agent whose center lies inside the box. Tiny
       * stray-click boxes are ignored (treat as cancel). */
      if (lw > 3 && lh > 3) {
        if (!dragging.additive) _topoSelectClear();
        var added = 0;
        Object.keys(_topoLastPositions.agents || {}).forEach(function (name) {
          var pos = _topoLastPositions.agents[name];
          if (!pos) return;
          if (
            pos.x >= lx &&
            pos.x <= lx + lw &&
            pos.y >= ly &&
            pos.y <= ly + lh
          ) {
            _topoSelectAdd(name);
            added++;
          }
        });
        if (added) {
          /* Nudge the signature so the next render reflects the new
           * .topo-agent-selected classes AND shows the action bar. */
          _topoLastSig = "";
          renderActivityTab();
        }
      }
    }
    svg.classList.remove("topo-zooming");
    svg.classList.remove("topo-panning");
    svg.classList.remove("topo-lassoing");
    dragging = null;
  });
  grid.addEventListener("dblclick", function (ev) {
    var svg = ev.target.closest && ev.target.closest(".topo-svg");
    if (!svg) return;
    /* Channel dblclick-to-compose is now handled by the click-counter
     * (_topoBumpClick with kind="channel") so that triple-click can
     * open Chat on the same node. Only plain empty-area dblclick
     * resets zoom here. */
    if (ev.target.closest(".topo-channel[data-channel]")) return;
    if (ev.target.closest(".topo-agent[data-agent]")) return;
    _resetVB(svg);
  });
  /* Button controls — back / minus / reset / plus. */
  grid.addEventListener("click", function (ev) {
    var btn = ev.target.closest(".topo-ctrl-btn[data-topo-ctrl]");
    if (!btn || !grid.contains(btn)) return;
    ev.stopPropagation();
    var svg = grid.querySelector(".topo-svg");
    if (!svg) return;
    var action = btn.getAttribute("data-topo-ctrl");
    if (action === "back") _popVB(svg);
    else if (action === "forward") _forwardVB(svg);
    else if (action === "reset") _resetVB(svg);
    else if (action === "plus") _zoomAt(svg, 1 / 1.25, null, null);
    else if (action === "minus") _zoomAt(svg, 1.25, null, null);
    else if (action === "integrate") {
      /* todo#305: 整列 — concentric ring auto-layout. */
      if (typeof _topoAutoLayout === "function") _topoAutoLayout();
      if (typeof renderActivityTab === "function") renderActivityTab();
    }
  });
  /* Keyboard — Escape = back; 0 = reset; +/= = zoom in; - = zoom out.
   * Only fires when an SVG is visible and no text input is focused. */
  document.addEventListener("keydown", function (ev) {
    var svg = document.querySelector(".activity-view-topology .topo-svg");
    if (!svg) return;
    var tag = (document.activeElement && document.activeElement.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    if (ev.key === "Escape") {
      /* Priority: cancel an in-flight drag before popping zoom history
       * — Escape should feel like "abort current gesture". */
      if (_topoDragState && _topoDragState.moved) {
        ev.preventDefault();
        _topoCleanupDrag();
        return;
      }
      ev.preventDefault();
      _popVB(svg);
    } else if (ev.key === "0") {
      ev.preventDefault();
      _resetVB(svg);
    } else if (ev.key === "+" || ev.key === "=") {
      ev.preventDefault();
      _zoomAt(svg, 1 / 1.25, null, null);
    } else if (ev.key === "-" || ev.key === "_") {
      ev.preventDefault();
      _zoomAt(svg, 1.25, null, null);
    }
  });
  /* Wheel interactions — standard GIS/CAD convention:
   *   ctrl + wheel  = cursor-anchored zoom (10% per tick)
   *   plain wheel   = vertical pan (deltaY)
   *   shift + wheel = horizontal pan (shift remaps deltaY to deltaX,
   *                   or deltaX from a trackpad is honored)
   * ywatanabe 2026-04-19: "mouse mid should allow shift to directions,
   * supporting horizontal and vertical move" / "ctrl scroll should
   * change the zoom". */
  grid.addEventListener(
    "wheel",
    function (ev) {
      var svg = ev.target.closest && ev.target.closest(".topo-svg");
      if (!svg) return;
      ev.preventDefault();
      if (ev.ctrlKey || ev.metaKey) {
        var p = _svgPoint(svg, ev.clientX, ev.clientY);
        var factor = ev.deltaY > 0 ? 1.1 : 1 / 1.1;
        _zoomAt(svg, factor, p.x, p.y);
        return;
      }
      /* Pan — translate the viewBox. Trackpads deliver deltaX natively;
       * a plain mouse wheel sends deltaY only, which we remap to
       * horizontal when Shift is held. Screen-space delta → viewBox-
       * space via the current scale. */
      var vb = _topoViewBox || { x: 0, y: 0, w: W, h: H };
      var svgW = svg.clientWidth || W;
      var svgH = svg.clientHeight || H;
      var sx = vb.w / svgW;
      var sy = vb.h / svgH;
      var deltaX = ev.deltaX;
      var deltaY = ev.deltaY;
      if (ev.shiftKey && deltaX === 0) {
        deltaX = deltaY;
        deltaY = 0;
      }
      _pushVB();
      _topoViewBox = {
        x: vb.x + deltaX * sx,
        y: vb.y + deltaY * sy,
        w: vb.w,
        h: vb.h,
      };
      _applyVB(svg, _topoViewBox);
    },
    { passive: false },
  );
}

