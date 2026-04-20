/* app/sidebar-memory-handlers.js — shared named handlers called by
 * BOTH the sidebar Memory section AND the Agents-tab pool's dropdown.
 * Extracted from sidebar-memory.js so the same behavior drives both
 * sites without duplication (2026-04-20 pool/sidebar unification pass).
 * Classic script; load BEFORE sidebar-memory.js so the wire step can
 * reference these helpers by name.
 */

/* Transient hint bubble anchored to any element — used when the user
 * clicks Save without picking an M-slot first. Auto-dismisses. */
function _sidebarMemoryShowHint(anchor, text) {
  if (!anchor) return;
  var old = document.querySelector(".sidebar-mem-hint");
  if (old && old.parentNode) old.parentNode.removeChild(old);
  var bubble = document.createElement("div");
  bubble.className = "sidebar-mem-hint";
  bubble.textContent = text;
  document.body.appendChild(bubble);
  var r = anchor.getBoundingClientRect();
  bubble.style.position = "fixed";
  bubble.style.left = Math.round(r.left) + "px";
  bubble.style.top = Math.round(r.bottom + 4) + "px";
  setTimeout(function () {
    if (bubble && bubble.parentNode) bubble.parentNode.removeChild(bubble);
  }, 1800);
}
window._sidebarMemoryShowHint = _sidebarMemoryShowHint;

/* After any memory-driven state change, refresh BOTH surfaces — the
 * sidebar itself AND the activity-tab pool. Pool refresh is done via
 * renderActivityTab when available; otherwise fall back to the
 * selection-paint helper so highlight stays in sync even when the
 * Agents tab isn't mounted. */
function _sidebarMemoryRefreshBothSurfaces() {
  renderSidebarMemory();
  if (typeof _topoLastSig !== "undefined") _topoLastSig = "";
  if (typeof renderActivityTab === "function") {
    renderActivityTab();
  }
  if (typeof _topoPoolSelectionPaint === "function") {
    _topoPoolSelectionPaint(document);
  }
  if (typeof _syncMemoryDirtyIndicators === "function") {
    _syncMemoryDirtyIndicators();
  }
}
window._sidebarMemoryRefreshBothSurfaces = _sidebarMemoryRefreshBothSurfaces;

/* Shared dropdown `change` handler — called from both the sidebar's
 * #sidebar-mem-select and the pool's #topo-pool-mem-select so the two
 * surfaces have IDENTICAL switching semantics (dirty-guard, "+ Create
 * new" prompt flow, "" = deactivate). */
function _memSelectOnChange(selectEl) {
  if (!selectEl) return;
  var val = selectEl.value;
  var prevSlot = _topoActiveMemSlot;
  var prevDirty =
    prevSlot != null &&
    typeof _topoPoolMemoryIsDirty === "function" &&
    _topoPoolMemoryIsDirty(prevSlot);
  if (prevDirty) {
    var ok = false;
    try {
      ok = window.confirm(
        "M" + prevSlot + " has unsaved changes. Discard them and switch?",
      );
    } catch (_e) {
      ok = false;
    }
    if (!ok) {
      /* Revert the dropdown value — re-render restores it. */
      _sidebarMemoryRefreshBothSurfaces();
      return;
    }
  }
  if (val === "") {
    _topoActiveMemSlot = null;
    if (typeof _topoPoolSelectClear === "function") {
      _topoPoolSelectClear();
    }
  } else if (val === "__new__") {
    var max =
      typeof _TOPO_POOL_MEM_MAX !== "undefined" ? _TOPO_POOL_MEM_MAX : 5;
    var free = 0;
    for (var i = 1; i <= max; i++) {
      if (!(_topoPoolMemories && _topoPoolMemories[String(i)])) {
        free = i;
        break;
      }
    }
    if (free === 0) {
      _sidebarMemoryShowHint(selectEl, "All slots full");
      _sidebarMemoryRefreshBothSurfaces();
      return;
    }
    var label = null;
    try {
      label = window.prompt("Name for M" + free + " (blank = unnamed):", "");
    } catch (_e) {
      label = null;
    }
    if (label === null) {
      _sidebarMemoryRefreshBothSurfaces();
      return;
    }
    _topoActiveMemSlot = free;
    if (typeof _topoPoolSelectClear === "function") {
      _topoPoolSelectClear();
    }
    if (
      String(label).trim() !== "" &&
      typeof _topoPoolMemoryRename === "function"
    ) {
      /* Create the slot with an empty snapshot so rename has something
       * to attach to, then rename. Save remains the user's explicit
       * action (no auto-save contract). */
      if (typeof _topoPoolMemorySave === "function") {
        _topoPoolMemorySave(free);
      }
      _topoPoolMemoryRename(free, String(label).trim());
    }
  } else {
    var slotN = parseInt(val, 10);
    if (slotN >= 1) {
      _topoActiveMemSlot = slotN;
      if (
        _topoPoolMemories &&
        _topoPoolMemories[String(slotN)] &&
        typeof _topoPoolMemoryRecall === "function"
      ) {
        _topoPoolMemoryRecall(slotN);
      }
    }
  }
  if (typeof _topoPersistActiveMemSlot === "function") {
    _topoPersistActiveMemSlot();
  }
  _sidebarMemoryRefreshBothSurfaces();
}
window._memSelectOnChange = _memSelectOnChange;

/* Shared "Save" action handler — returns true when save went through,
 * false when blocked with a hint (no active slot). Anchor is the
 * button element the hint bubble should anchor to. */
function _memSaveActionHandler(anchor) {
  if (_topoActiveMemSlot == null) {
    _sidebarMemoryShowHint(anchor, "Pick an M-slot first");
    return false;
  }
  if (typeof _topoPoolMemorySave === "function") {
    _topoPoolMemorySave(_topoActiveMemSlot);
  }
  return true;
}
window._memSaveActionHandler = _memSaveActionHandler;
