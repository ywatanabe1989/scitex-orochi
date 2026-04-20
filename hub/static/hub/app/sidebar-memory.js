/* app/sidebar-memory.js — sidebar Memory section wiring. Thin
 * orchestrator: markup builders + renderSidebarMemory live in
 * sidebar-memory-options.js; shared change/save helpers live in
 * sidebar-memory-handlers.js (both loaded BEFORE this file). This file
 * only holds the DOM-event wiring (delegated click + contextmenu +
 * select change) for the sidebar host element. Mirrors the pool's
 * behavior via the shared handlers so ywatanabe 2026-04-20 "the pool
 * strip must use the EXACT same control as the sidebar" directive
 * holds end-to-end. Classic script — no ES module semantics.
 */

/* Delegated click handler on the sidebar Memory section. Matches the
 * semantics of grid-click.js's pool strip: plain click on a chip
 * toggles recall/active; shift-click saves; action buttons map to
 * select-all / deselect-all / none / save. */
function _wireSidebarMemory() {
  var host = document.getElementById("sidebar-memory");
  if (!host) return;
  if (host._mwWired) return;
  host._mwWired = true;

  /* Dropdown change — switches active slot. Delegates to the shared
   * _memSelectOnChange() so the pool's dropdown uses identical logic
   * (dirty-guard, "+ Create new" prompt flow, "" = deactivate). */
  var selectEl = host.querySelector("#sidebar-mem-select");
  if (selectEl) {
    selectEl.addEventListener("change", function (ev) {
      _memSelectOnChange(selectEl);
      ev.stopPropagation();
    });
  }

  host.addEventListener("click", function (ev) {
    var chip = ev.target.closest(".sidebar-mem-btn[data-mem-slot]");
    if (chip && host.contains(chip)) {
      var slotN = parseInt(chip.getAttribute("data-mem-slot"), 10);
      var max =
        typeof _TOPO_POOL_MEM_MAX !== "undefined" ? _TOPO_POOL_MEM_MAX : 5;
      if (!(slotN >= 1 && slotN <= max)) return;
      if (ev.shiftKey) {
        if (typeof _topoPoolMemorySave === "function") {
          _topoPoolMemorySave(slotN);
        }
      } else {
        /* Toggle active slot with the same semantics as the pool: if
         * this slot is already active, deactivate; otherwise activate
         * + recall if occupied. Empty-slot activation does NOT seed
         * (2026-04-20 no-autosave contract). */
        if (_topoActiveMemSlot === slotN) {
          _topoActiveMemSlot = null;
        } else {
          _topoActiveMemSlot = slotN;
          if (
            _topoPoolMemories &&
            _topoPoolMemories[String(slotN)] &&
            typeof _topoPoolMemoryRecall === "function"
          ) {
            _topoPoolMemoryRecall(slotN);
          }
        }
        if (typeof _topoPersistActiveMemSlot === "function") {
          _topoPersistActiveMemSlot();
        }
      }
      ev.stopPropagation();
      _sidebarMemoryRefreshBothSurfaces();
      return;
    }

    var actBtn = ev.target.closest(
      ".sidebar-memory-actions button[data-action]",
    );
    if (actBtn && host.contains(actBtn)) {
      var action = actBtn.getAttribute("data-action");
      if (action === "none") {
        _topoActiveMemSlot = null;
        if (typeof _topoPersistActiveMemSlot === "function") {
          _topoPersistActiveMemSlot();
        }
        if (typeof _topoPoolSelectClear === "function") {
          _topoPoolSelectClear();
        }
      } else if (action === "select-all") {
        if (typeof _topoPoolSelectAll === "function") {
          /* Prefer the topology grid as the chip host so the "visible
           * chip set" scoping matches the pool's Select-All behavior.
           * Fall back to document so the sidebar action still does
           * something when the Agents tab isn't mounted. */
          var grid = document.getElementById("activity-grid");
          _topoPoolSelectAll(grid || document);
        }
      } else if (action === "deselect-all") {
        if (typeof _topoPoolSelectClear === "function") {
          _topoPoolSelectClear();
        }
      } else if (action === "save") {
        var ok = _memSaveActionHandler(actBtn);
        if (!ok) {
          ev.stopPropagation();
          return;
        }
      }
      ev.stopPropagation();
      _sidebarMemoryRefreshBothSurfaces();
      return;
    }
  });

  /* Right-click on a chip → rename / clear — mirrors grid-ctx.js on
   * the pool. Empty slot is a no-op (nothing to rename). */
  host.addEventListener("contextmenu", function (ev) {
    if (ev.shiftKey) return;
    var chip = ev.target.closest(".sidebar-mem-btn[data-mem-slot]");
    if (!chip || !host.contains(chip)) return;
    var slotN = parseInt(chip.getAttribute("data-mem-slot"), 10);
    var max =
      typeof _TOPO_POOL_MEM_MAX !== "undefined" ? _TOPO_POOL_MEM_MAX : 5;
    if (!(slotN >= 1 && slotN <= max)) return;
    var mem = _topoPoolMemories && _topoPoolMemories[String(slotN)];
    if (!mem) return;
    ev.preventDefault();
    ev.stopPropagation();
    var curLabel = mem.label && typeof mem.label === "string" ? mem.label : "";
    var answer = null;
    try {
      answer = window.prompt(
        "Rename M" + slotN + " (leave empty to clear the slot):",
        curLabel,
      );
    } catch (_e) {
      answer = null;
    }
    if (answer === null) return;
    var trimmed = String(answer).trim();
    if (trimmed === "") {
      if (typeof _topoPoolMemoryDelete === "function") {
        _topoPoolMemoryDelete(slotN);
      }
    } else {
      if (typeof _topoPoolMemoryRename === "function") {
        _topoPoolMemoryRename(slotN, trimmed);
      }
    }
    _sidebarMemoryRefreshBothSurfaces();
  });
}

document.addEventListener("DOMContentLoaded", function () {
  _wireSidebarMemory();
  renderSidebarMemory();
});
