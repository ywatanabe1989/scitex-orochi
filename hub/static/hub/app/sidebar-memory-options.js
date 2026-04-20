/* app/sidebar-memory-options.js — dropdown <option> / legacy chip
 * row markup builders + the renderSidebarMemory() orchestrator. Split
 * out of sidebar-memory.js so the click/context wiring stays under the
 * 512-line .js hook cap. Loads BEFORE sidebar-memory-handlers.js and
 * sidebar-memory.js. Classic script — no ES module semantics.
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
window._buildSidebarMemoryDropdownOptions = _buildSidebarMemoryDropdownOptions;

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
window._buildSidebarMemoryChipsHtml = _buildSidebarMemoryChipsHtml;

/* Shared "Save" button state helper — used for both the sidebar and
 * the pool Save buttons so their label + armed state track exactly
 * the same _topoActiveMemSlot + selection-size inputs. */
function _updateMemorySaveBtn(saveBtn) {
  if (!saveBtn) return;
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
window._updateMemorySaveBtn = _updateMemorySaveBtn;

/* Rebuild the sidebar Memory section from shared pool state. Also
 * mirrors the dropdown into the Agents-tab pool's own select element
 * (`#topo-pool-mem-select`) and updates the pool's Save button, so the
 * two surfaces stay in lockstep without each needing their own render
 * pass. Safe to call when either host DOM isn't in the page — missing
 * nodes become no-ops. */
function renderSidebarMemory() {
  var optionsHtml = _buildSidebarMemoryDropdownOptions();

  var host = document.getElementById("sidebar-memory");
  if (host) {
    /* Dropdown picker (current UI) — replaced the 5-chip row per
     * ywatanabe 2026-04-20: "use dropdown instead of buttons". */
    var selectEl = host.querySelector("#sidebar-mem-select");
    if (selectEl) {
      selectEl.innerHTML = optionsHtml;
    }
    /* Legacy chip row (if the template still has one — never true post-
     * 2026-04-20 template). */
    var slotsEl = host.querySelector(".sidebar-memory-slots");
    if (slotsEl && !selectEl) {
      slotsEl.innerHTML = _buildSidebarMemoryChipsHtml();
    }
    _updateMemorySaveBtn(
      host.querySelector('.sidebar-memory-actions button[data-action="save"]'),
    );
  }

  /* Mirror into the Agents-tab pool select if it's mounted. Same
   * options HTML, same Save-button affordance. ywatanabe 2026-04-20
   * unification pass — "the pool strip must use the EXACT same
   * control as the sidebar". */
  var poolSelect = document.getElementById("topo-pool-mem-select");
  if (poolSelect) {
    poolSelect.innerHTML = optionsHtml;
    var poolHost = poolSelect.closest(".topo-pool-actions");
    if (poolHost) {
      _updateMemorySaveBtn(
        poolHost.querySelector(
          '.sidebar-memory-actions button[data-action="save"]',
        ),
      );
    }
  }
}
window.renderSidebarMemory = renderSidebarMemory;
