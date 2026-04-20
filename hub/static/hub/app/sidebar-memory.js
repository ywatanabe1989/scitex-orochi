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

/* Build the <option> list for the memory dropdown. Each occupied slot
 * shows "M<n> · label · count" (dirty-dot suffix when the active slot
 * has unsaved edits); empty slots show "M<n> (empty)". A trailing
 * "+ Create new" option jumps to the next free slot + prompts for a
 * label. */
function _buildSidebarMemoryDropdownOptions() {
  var max = typeof _TOPO_POOL_MEM_MAX !== "undefined" ? _TOPO_POOL_MEM_MAX : 5;
  var active = _topoActiveMemSlot;
  var parts = [];
  /* "No memory" — the unselected / unfiltered baseline. */
  var noneSel = active == null ? ' selected="selected"' : "";
  parts.push('<option value=""' + noneSel + ">No memory</option>");
  var firstFree = 0;
  for (var slot = 1; slot <= max; slot++) {
    var mem = _topoPoolMemories ? _topoPoolMemories[String(slot)] : null;
    if (!mem && firstFree === 0) firstFree = slot;
    var label = mem && mem.label ? String(mem.label) : "";
    var count = mem
      ? (mem.agents || []).length + (mem.channels || []).length
      : 0;
    var isActive = active === slot;
    var dirty =
      isActive &&
      typeof _topoPoolMemoryIsDirty === "function" &&
      _topoPoolMemoryIsDirty(slot);
    var face;
    if (mem) {
      face = "M" + slot;
      if (label) face += " \u00b7 " + label;
      if (count > 0) face += " (" + count + ")";
    } else {
      face = "M" + slot + " (empty)";
    }
    if (dirty) face += " \u25CF";
    var sel = isActive ? ' selected="selected"' : "";
    parts.push(
      '<option value="' +
        slot +
        '"' +
        sel +
        ">" +
        escapeHtml(face) +
        "</option>",
    );
  }
  /* "+ Create new" — disabled when all slots are full. */
  if (firstFree > 0) {
    parts.push('<option value="__new__">+ Create new</option>');
  } else {
    parts.push('<option value="__full__" disabled>(all slots full)</option>');
  }
  return parts.join("");
}

/* Build the HTML for the M1..M5 chip row. LEGACY — kept in case other
 * call-sites reference it; not used by the dropdown renderer. */
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
  /* Dropdown picker (current UI) — replaced the 5-chip row per
   * ywatanabe 2026-04-20: "use dropdown instead of buttons". */
  var selectEl = host.querySelector("#sidebar-mem-select");
  if (selectEl) {
    selectEl.innerHTML = _buildSidebarMemoryDropdownOptions();
  }
  /* Legacy chip row (if the template still has one — never true post-
   * 2026-04-20 template). */
  var slotsEl = host.querySelector(".sidebar-memory-slots");
  if (slotsEl && !selectEl) {
    slotsEl.innerHTML = _buildSidebarMemoryChipsHtml();
  }
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

  /* Dropdown change — switches active slot. Guards:
   *   - If the current active slot is dirty, confirm() before leaving
   *     (otherwise a casual switch silently loses edits since we're on
   *     an explicit-save contract — ywatanabe 2026-04-20).
   *   - "__new__" takes the next free slot and prompts for a label; the
   *     new slot starts empty so the user can Save into it.
   *   - "" (No memory) deactivates + clears the pool selection. */
  var selectEl = host.querySelector("#sidebar-mem-select");
  if (selectEl) {
    selectEl.addEventListener("change", function (ev) {
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
          label = window.prompt(
            "Name for M" + free + " (blank = unnamed):",
            "",
          );
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
          /* Create the slot with an empty snapshot so rename has
           * something to attach to, then rename. Save remains the
           * user's explicit action (no auto-save contract). */
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
