// @ts-nocheck
// Migrated classic-script file. Types intentionally loose during
// the big-bang JS-to-TS bundle migration. Narrow later, per-file.
/* activity-tab/grid-delegation.js — delegated listeners on the
 * overview grid. Per-handler code lives in grid-click.js / grid-mouse.js
 * / grid-ctx.js / grid-hover.js; this file just wires them up once
 * (guard flag) and defines the standalone _topoSvgPoint helper used
 * by both zoom/pan and drag gestures. */


function _wireOverviewGridDelegation(grid) {
  if (_overviewGridWired || !grid) return;
  _ovgWireClick(grid);
  _ovgWireMouse(grid);
  _ovgWireContextmenu(grid);
  _ovgWireHover(grid);
  _overviewGridWired = true;
}

/* Standalone copy of the client→SVG-point transform (the one inside
 * _wireTopoZoomPan is scoped). Kept separate so both wire helpers can
 * use it without sharing closure state. */
function _topoSvgPoint(svg, clientX, clientY) {
  if (!svg || !svg.createSVGPoint) return { x: clientX, y: clientY };
  var pt = svg.createSVGPoint();
  pt.x = clientX;
  pt.y = clientY;
  var m = svg.getScreenCTM();
  if (!m) return { x: clientX, y: clientY };
  return pt.matrixTransform(m.inverse());
}
