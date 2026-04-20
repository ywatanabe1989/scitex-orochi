/* app/sidebar-memory.js — sidebar Memory section renderer + click
 * wiring. Mirrors the Agents-tab topology pool's memory strip so users
 * can recall/save M1..M5 selection snapshots without switching tabs.
 * Shares state with the pool via the window-global _topoPoolMemories,
 * _topoActiveMemSlot, _topoPoolSelection so both surfaces stay in
 * lockstep. Renders only when the host DOM is present. Classic script
 * — no ES module semantics.
 *
 * Change 2 of the 2026-04-20 explicit-save memory-UX pass (Change 1 =
 * agent SVG badge 39d2a50; Change 3 = no-autosave + dirty dot 6921695).
 */

/* Build the HTML for the M1..M5 chip row. Kept as a pure string
 * builder so innerHTML assignment is a single write. */
function _buildSidebarMemoryChipsHtml() {
  var html = "";
  var max = typeof _TOPO_POOL_MEM_MAX !== "undefined" ? _TOPO_POOL_MEM_MAX : 5;
  for (var slot = 1; slot <= max; slot++) {
    var mem = _topoPoolMemories ? _topoPoolMemories[String(slot)] : null;
    var count = mem
      ? (mem.agents || []).length + (mem.channels || []).length
      : 0;
    var hiddenCount =
      mem && mem.hidden
        ? (mem.hidden.agents || []).length + (mem.hidden.channels || []).length
        : 0;
    var filterActive = !!(
      mem &&
      mem.filter &&
      ((mem.filter.input && mem.filter.input.length) ||
        (Array.isArray(mem.filter.tags) && mem.filter.tags.length))
    );
    var label = mem && mem.label ? String(mem.label) : "";
    var active = _topoActiveMemSlot === slot;
    var dirty =
      active &&
      typeof _topoPoolMemoryIsDirty === "function" &&
      _topoPoolMemoryIsDirty(slot);
    /* Face: label when present (trim to 5 chars + ellipsis), otherwise
     * "M<slot>" with optional count suffix. Matches the pool button
     * convention so the two surfaces read the same at a glance. */
    var face;
    if (label) {
      face = label.length > 6 ? label.slice(0, 5) + "\u2026" : label;
    } else if (mem && count > 0) {
      face = "M" + slot + "\u00b7" + count;
    } else {
      face = "M" + slot;
    }
    var dirtyDot = dirty ? " \u25CF" : "";
    /* Tooltip: full composition. Mirrors the pool tooltip wording so
     * users see the same summary in both places. */
    var title;
    if (mem) {
      var parts = [];
      parts.push(count + " selected");
      if (hiddenCount) parts.push(hiddenCount + " hidden");
      if (filterActive) parts.push("filter");
      title =
        "Recall M" +
        slot +
        (label ? " — " + label : "") +
        " (" +
        parts.join(", ") +
        "). Shift+click to overwrite, right-click to rename or clear.";
    } else {
      title =
        "M" +
        slot +
        " (empty). Click Save below, or shift-click this chip, to snapshot the current selection.";
    }
    if (dirty) title += "\n\nUnsaved changes — click Save to persist";
    var cls = "sidebar-mem-btn sidebar-mem-chip";
    if (mem) cls += " sidebar-mem-btn-filled sidebar-mem-chip-filled";
    if (label) cls += " sidebar-mem-chip-labeled";
    if (active) cls += " sidebar-mem-btn-active sidebar-mem-chip-active";
    if (dirty) cls += " sidebar-mem-btn-dirty sidebar-mem-chip-dirty";
    html +=
      '<button type="button" class="' +
      cls +
      '" data-mem-slot="' +
      slot +
      '" title="' +
      escapeHtml(title) +
      '">' +
      escapeHtml(face) +
      dirtyDot +
      "</button>";
  }
  return html;
}

/* Rebuild the sidebar Memory section from shared pool state. Safe to
 * call when the host DOM isn't in the page — becomes a no-op. */
function renderSidebarMemory() {
  var host = document.getElementById("sidebar-memory");
  if (!host) return;
  var slotsEl = host.querySelector(".sidebar-memory-slots");
  if (!slotsEl) return;
  slotsEl.innerHTML = _buildSidebarMemoryChipsHtml();
  /* Keep "Save" disabled-looking when nothing selected AND no active
   * slot, so the button's affordance tracks whether there's something
   * to persist. We don't actually disable the button — a click still
   * shows the "Pick an M-slot first" hint. */
  var saveBtn = host.querySelector(
    '.sidebar-memory-actions button[data-action="save"]',
  );
  if (saveBtn) {
    var hasSel =
      typeof _topoPoolSelectionSize === "function" &&
      _topoPoolSelectionSize() > 0;
    saveBtn.classList.toggle(
      "sidebar-mem-btn-armed",
      hasSel || _topoActiveMemSlot != null,
    );
    /* Dynamic label — "Save to M{n}" when a slot is active makes
     * the target obvious; falls back to "Save" with a hint on
     * click when no slot is picked. */
    saveBtn.textContent =
      _topoActiveMemSlot != null ? "Save to M" + _topoActiveMemSlot : "Save";
  }
}
window.renderSidebarMemory = renderSidebarMemory;

/* Transient hint bubble anchored to the Save button — used when the
 * user clicks Save without picking an M-slot first. Auto-dismisses. */
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

/* After any sidebar-initiated state change, refresh BOTH surfaces —
 * the sidebar itself AND the activity-tab pool. Pool refresh is done
 * via renderActivityTab when available; otherwise fall back to the
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

/* Delegated click handler on the sidebar Memory section. Matches the
 * semantics of grid-click.js's pool strip: plain click on a chip
 * toggles recall/active; shift-click saves; action buttons map to
 * select-all / deselect-all / none / save. */
function _wireSidebarMemory() {
  var host = document.getElementById("sidebar-memory");
  if (!host) return;
  if (host._mwWired) return;
  host._mwWired = true;

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
        if (_topoActiveMemSlot == null) {
          _sidebarMemoryShowHint(actBtn, "Pick an M-slot first");
          ev.stopPropagation();
          return;
        }
        if (typeof _topoPoolMemorySave === "function") {
          _topoPoolMemorySave(_topoActiveMemSlot);
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
