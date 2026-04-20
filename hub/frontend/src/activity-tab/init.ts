// @ts-nocheck
// Migrated classic-script file. Types intentionally loose during
// the big-bang JS-to-TS bundle migration. Narrow later, per-file.
/* activity-tab/init.js — renderActivityTab entry point, tab-click
 * wiring, auto-refresh timer. */

function renderActivityTab() {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var grid = document.getElementById("activity-grid");
  var summary = document.getElementById("activity-summary");
  if (!grid) return;

  _wireTopoEscCancel();
  _wireOverviewControls();
  _applyOverviewViewClass(grid);

  var src = window.__lastAgents || [];
  if (!src.length) {
    grid.innerHTML = '<p class="empty-notice">No agents connected.</p>';
    if (summary) summary.textContent = "";
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try {
        msgInput.setSelectionRange(savedStart, savedEnd);
      } catch (_) {}
    }
    return;
  }

  /* Sort: pinned always first (they're "locked to the top"), then by
   * the user-selected key. Same ordering rule is intended to apply to
   * future topology/connection-map view too. */
  var agents = src.slice().sort(function (a, b) {
    var pa = a.pinned ? 0 : 1;
    var pb = b.pinned ? 0 : 1;
    if (pa !== pb) return pa - pb;
    var ka, kb;
    if (_overviewSort === "machine") {
      ka = (a.machine || "") + "/" + (a.name || "");
      kb = (b.machine || "") + "/" + (b.name || "");
    } else {
      ka = a.name || "";
      kb = b.name || "";
    }
    return ka.localeCompare(kb);
  });

  if (_overviewFilter) {
    var q = _overviewFilter.toLowerCase();
    agents = agents.filter(function (a) {
      var hay = (
        (a.name || "") +
        " " +
        (a.machine || "") +
        " " +
        (a.role || "")
      ).toLowerCase();
      return hay.indexOf(q) !== -1;
    });
  }

  _renderActivityCards(agents, grid);

  /* Mirror pool memory state into the sidebar Memory section so the two
   * surfaces stay in lockstep (same _topoPoolMemories store). No-op
   * when sidebar-memory.js / #sidebar-memory are not loaded. */
  if (typeof renderSidebarMemory === "function") {
    renderSidebarMemory();
  }

  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
}

document.addEventListener("DOMContentLoaded", function () {
  var btn = document.querySelector('[data-tab="activity"]');
  if (btn) {
    btn.addEventListener("click", function () {
      refreshActivityFromApi();
      startActivityAutoRefresh();
    });
  }
});
