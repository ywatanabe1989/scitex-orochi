// @ts-nocheck
import { _ovgWireClick } from "./grid-click";
import { _ovgWireContextmenu } from "./grid-ctx";
import { _ovgWireHover } from "./grid-hover";
import { _ovgWireMouse } from "./grid-mouse";
import { _memSelectOnChange } from "../app/sidebar-memory-handlers";

/* activity-tab/grid-delegation.js — delegated listeners on the
 * overview grid. Per-handler code lives in grid-click.js / grid-mouse.js
 * / grid-ctx.js / grid-hover.js; this file just wires them up once
 * (guard flag) and defines the standalone _topoSvgPoint helper used by
 * both zoom/pan and drag gestures.
 *
 * msg#16319 (ywatanabe msg#16317): the channel-hover-preview popover
 * (PR #311 task 11) is removed — the double-click graph-compose popup
 * is the primary path for peeking at / replying to a channel, so the
 * hover preview is redundant. */

export function _wireOverviewGridDelegation(grid) {
  if ((globalThis as any)._overviewGridWired || !grid) return;
  _ovgWireClick(grid);
  _ovgWireMouse(grid);
  _ovgWireContextmenu(grid);
  _ovgWireHover(grid);
  _ovgWireChange(grid);
  (globalThis as any)._overviewGridWired = true;
}

/* Delegated `change` listener — the pool's memory dropdown
 * (#topo-pool-mem-select) re-renders on every topology refresh, so a
 * fresh listener on each render would leak. Delegation on the grid
 * catches the event regardless of how many times the <select> is
 * re-created. Routes through the shared _memSelectOnChange so both
 * surfaces have IDENTICAL switching semantics (2026-04-20
 * pool/sidebar unification). */
export function _ovgWireChange(grid) {
  grid.addEventListener("change", function (ev) {
    var poolSel = ev.target.closest("#topo-pool-mem-select");
    if (poolSel && grid.contains(poolSel)) {
      if (typeof _memSelectOnChange === "function") {
        _memSelectOnChange(poolSel);
      }
      ev.stopPropagation();
      return;
    }
  });
}

/* Standalone copy of the client→SVG-point transform (the one inside
 * _wireTopoZoomPan is scoped). Kept separate so both wire helpers can
 * use it without sharing closure state. */
export function _topoSvgPoint(svg, clientX, clientY) {
  if (!svg || !svg.createSVGPoint) return { x: clientX, y: clientY };
  var pt = svg.createSVGPoint();
  pt.x = clientX;
  pt.y = clientY;
  var m = svg.getScreenCTM();
  if (!m) return { x: clientX, y: clientY };
  return pt.matrixTransform(m.inverse());
}
