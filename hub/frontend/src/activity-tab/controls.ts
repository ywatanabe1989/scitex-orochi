// @ts-nocheck
import { _topoCleanupDrag } from "./compose";
import { renderActivityTab } from "./init";
import { fetchAgents } from "../app/sidebar-agents";

/* activity-tab/controls.js — sort/view/color/size dropdown wiring
 * + universal Escape-cancel for the topology canvas. */

export var _overviewControlsWired = false;
export function _wireOverviewControls() {
  if (_overviewControlsWired) return;
  var sortSelect = document.getElementById("activity-sort-select");
  var viewSwitch = document.querySelector(".activity-view-switch");
  var colorSelect = document.getElementById("activity-color-select");
  var sizeSelect = document.getElementById("activity-size-select");
  if (!sortSelect || !viewSwitch) return;
  sortSelect.value = (globalThis as any)._overviewSort;
  /* Legacy localStorage value "tiled" -> fall back to "list" since the
   * switch is now binary (Viz / List). "topology" still accepted. */
  if ((globalThis as any)._overviewView !== "list" && (globalThis as any)._overviewView !== "topology")
    (globalThis as any)._overviewView = "list";
  if (colorSelect) colorSelect.value = (globalThis as any)._overviewColor;
  if (sizeSelect) sizeSelect.value = (globalThis as any)._topoSizeBy;
  /* Filter input removed — users filter via the global Ctrl+K fuzzy
   * search which already applies across every tab (ywatanabe 2026-04-
   * 19: "filtering should be always Ctrl K in the scope"). The module
   * var (globalThis as any)._overviewFilter stays zero so the old filter logic is a no-op. */
  (globalThis as any)._overviewFilter = "";
  function _setViewBtnActive() {
    viewSwitch
      .querySelectorAll(".activity-view-switch-btn")
      .forEach(function (b) {
        b.classList.toggle(
          "active",
          b.getAttribute("data-view") === (globalThis as any)._overviewView,
        );
      });
  }
  _setViewBtnActive();
  sortSelect.addEventListener("change", function () {
    (globalThis as any)._overviewSort = sortSelect.value;
    try {
      localStorage.setItem("orochi.overviewSort", (globalThis as any)._overviewSort);
    } catch (_e) {}
    renderActivityTab();
    /* The sort dropdown now also drives the sidebar AGENTS list
     * (ywatanabe 2026-04-21). Re-run fetchAgents on the existing
     * cached payload so the new order takes effect without waiting
     * for the next heartbeat. */
    if (typeof fetchAgents === "function") fetchAgents();
  });
  viewSwitch.addEventListener("click", function (ev) {
    var btn = ev.target.closest(".activity-view-switch-btn[data-view]");
    if (!btn) return;
    var next = btn.getAttribute("data-view");
    if (next === (globalThis as any)._overviewView) return;
    (globalThis as any)._overviewView = next;
    try {
      localStorage.setItem("orochi.overviewView", (globalThis as any)._overviewView);
    } catch (_e) {}
    _setViewBtnActive();
    renderActivityTab();
  });
  if (colorSelect) {
    colorSelect.addEventListener("change", function () {
      (globalThis as any)._overviewColor = colorSelect.value;
      try {
        localStorage.setItem("orochi.overviewColor", (globalThis as any)._overviewColor);
      } catch (_e) {}
      renderActivityTab();
      /* Sidebar color keying also follows this dropdown now. */
      if (typeof fetchAgents === "function") fetchAgents();
    });
  }
  if (sizeSelect) {
    sizeSelect.addEventListener("change", function () {
      (globalThis as any)._topoSizeBy = sizeSelect.value;
      try {
        localStorage.setItem("orochi.topoSizeBy", (globalThis as any)._topoSizeBy);
      } catch (_e) {}
      /* Invalidate topology signature cache so the channel radii
       * actually recompute on the next render (topology short-circuits
       * when the signature string hasn't changed). */
      (globalThis as any)._topoLastSig = "";
      renderActivityTab();
    });
  }
  _overviewControlsWired = true;
}

/* Universal Escape-cancel for the topology canvas.
 *   - Closes open context menus (agent / channel) if the respective
 *     _hide*CtxMenu helpers are exposed by app.js.
 *   - Cancels an in-flight drag-subscribe gesture via _topoCleanupDrag.
 *   - Hides any active rectangle-zoom or lasso overlay so a half-drawn
 *     selection doesn't leave ghost rectangles on-screen.
 * Bound once (guarded by _topoEscWired) at document level in capture
 * phase so it fires before per-widget handlers. Text-input focus is
 * respected — we early-return when an editable element is focused so
 * users can still Escape out of inputs without triggering these.
 * ywatanabe 2026-04-19. */
export var _topoEscWired = false;
export function _wireTopoEscCancel() {
  if (_topoEscWired) return;
  _topoEscWired = true;
  document.addEventListener(
    "keydown",
    function (ev) {
      if (ev.key !== "Escape") return;
      var t = ev.target;
      if (t) {
        var tag = (t.tagName || "").toUpperCase();
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
        if (t.isContentEditable) return;
      }
      /* Close any open context menus first. */
      if (typeof window._hideAgentCtxMenu === "function") {
        try {
          window._hideAgentCtxMenu();
        } catch (_) {}
      }
      if (typeof window._hideChannelCtxMenu === "function") {
        try {
          window._hideChannelCtxMenu();
        } catch (_) {}
      }
      /* Cancel in-flight topology drag (subscribe-by-drag). */
      if (typeof (globalThis as any)._topoDragState !== "undefined" && (globalThis as any)._topoDragState) {
        try {
          _topoCleanupDrag();
        } catch (_) {}
      }
      /* Hide any lingering rectangle-zoom / lasso overlay rects. The
       * actual `dragging` state lives in _wireTopoZoomPan's closure and
       * isn't reachable from here, but hiding the visual overlay is the
       * user-visible cancel — the next mouseup will reset the closure. */
      var zb = document.querySelector(".topo-svg .topo-zoombox");
      if (zb) zb.style.display = "none";
      var lz = document.querySelector(".topo-svg .topo-lasso");
      if (lz) lz.style.display = "none";
      var svg = document.querySelector(".topo-svg");
      if (svg) {
        svg.classList.remove("topo-zooming");
        svg.classList.remove("topo-panning");
        svg.classList.remove("topo-lassoing");
      }
    },
    { capture: true },
  );
}
