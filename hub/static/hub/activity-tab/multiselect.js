/* activity-tab/multiselect.js — canvas multi-select (_topoSelected)
 * + left-pool selection helpers + memory slots snapshot/save/recall
 * /delete + selection paint + canvas pool-as-filter. */

/* Multi-select state for the topology. A Set of agent names currently
 * selected; the renderer adds `.topo-agent-selected` to matching nodes
 * and the floating action bar appears when size ≥ 2. */
var _topoSelected = Object.create(null); /* name → true */
function _topoSelectedNames() {
  return Object.keys(_topoSelected);
}
function _topoSelectClear() {
  _topoSelected = Object.create(null);
}
function _topoSelectToggle(name) {
  if (_topoSelected[name]) delete _topoSelected[name];
  else _topoSelected[name] = true;
}
function _topoSelectAdd(name) {
  if (name) _topoSelected[name] = true;
}

function _topoPersistActiveMemSlot() {
  try {
    if (_topoActiveMemSlot == null)
      localStorage.removeItem(_TOPO_ACTIVE_MEM_KEY);
    else localStorage.setItem(_TOPO_ACTIVE_MEM_KEY, String(_topoActiveMemSlot));
  } catch (_) {}
}
/* Auto-save REMOVED 2026-04-20 per user directive: "explicit save only,
 * NO auto-save". The previous behavior silently overwrote the active
 * slot on every selection change, which made accidental clobbering
 * trivial. Explicit Save button is the only persistence path now.
 * _topoPoolMemoryIsDirty() below is what the UI uses to signal unsaved
 * state on a slot chip / Save button. */
function _topoAutoSaveActiveSlot() {
  /* intentional no-op — retained as a stub so call sites that used to
   * trigger auto-save (e.g. _topoSaveHidden in state.js) keep working
   * without becoming "unsaved dirt" producers mid-operation. */
}

/* Dirty-state check: compare the current _topoPoolSelection to the
 * saved snapshot in the given memory slot. Used by sidebar Memory
 * section + pool memory strip to show a dirty dot on slots whose
 * contents no longer match the live selection (so users see at a
 * glance which slots need a Save click). Returns true if dirty. */
function _topoPoolMemoryIsDirty(slot) {
  var mem = _topoPoolMemories[String(slot)];
  if (!mem) return false;
  var savedA = {};
  (mem.agents || []).forEach(function (n) {
    savedA[n] = true;
  });
  var savedC = {};
  (mem.channels || []).forEach(function (n) {
    savedC[n] = true;
  });
  var liveA = _topoPoolSelection.agents || {};
  var liveC = _topoPoolSelection.channels || {};
  var liveAKeys = Object.keys(liveA);
  var liveCKeys = Object.keys(liveC);
  if (liveAKeys.length !== Object.keys(savedA).length) return true;
  if (liveCKeys.length !== Object.keys(savedC).length) return true;
  for (var i = 0; i < liveAKeys.length; i++) {
    if (!savedA[liveAKeys[i]]) return true;
  }
  for (var j = 0; j < liveCKeys.length; j++) {
    if (!savedC[liveCKeys[j]]) return true;
  }
  return false;
}

function _topoPoolPersistSelection() {
  try {
    localStorage.setItem(
      _TOPO_POOL_SEL_KEY,
      JSON.stringify({
        agents: Object.keys(_topoPoolSelection.agents),
        channels: Object.keys(_topoPoolSelection.channels),
      }),
    );
  } catch (_e) {
    /* quota / private mode — selection still works for the session. */
  }
  /* No auto-save — see _topoAutoSaveActiveSlot() stub above. */
  if (typeof _syncMemoryDirtyIndicators === "function") {
    _syncMemoryDirtyIndicators();
  }
}
function _topoPoolPersistMemories() {
  try {
    localStorage.setItem(
      _topoMemWorkspaceKey(),
      JSON.stringify(_topoPoolMemories),
    );
  } catch (_e) {
    /* ignore */
  }
}

function _topoPoolSelectionSize() {
  return (
    Object.keys(_topoPoolSelection.agents).length +
    Object.keys(_topoPoolSelection.channels).length
  );
}
function _topoPoolSelectionHas(kind, name) {
  var bucket = kind === "channel" ? "channels" : "agents";
  return !!_topoPoolSelection[bucket][name];
}
function _topoPoolSelectToggle(kind, name) {
  var bucket = kind === "channel" ? "channels" : "agents";
  if (_topoPoolSelection[bucket][name]) delete _topoPoolSelection[bucket][name];
  else _topoPoolSelection[bucket][name] = true;
  _topoPoolPersistSelection();
}
function _topoPoolSelectClear() {
  _topoPoolSelection = {
    agents: Object.create(null),
    channels: Object.create(null),
  };
  _topoPoolPersistSelection();
}
function _topoPoolSelectOnly(kind, name) {
  _topoPoolSelection = {
    agents: Object.create(null),
    channels: Object.create(null),
  };
  var bucket = kind === "channel" ? "channels" : "agents";
  _topoPoolSelection[bucket][name] = true;
  _topoPoolPersistSelection();
}
/* Select all agents + channels currently rendered as chips in the pool
 * (we scope to the visible chip set rather than the full universe so
 * hidden chips stay out unless the user explicitly unhides them). */
function _topoPoolSelectAll(grid) {
  var host = grid || document;
  var chips = host.querySelectorAll(".topo-pool-chip");
  _topoPoolSelection = {
    agents: Object.create(null),
    channels: Object.create(null),
  };
  for (var i = 0; i < chips.length; i++) {
    var chip = chips[i];
    var ag = chip.getAttribute("data-agent");
    var ch = chip.getAttribute("data-channel");
    if (ag) _topoPoolSelection.agents[ag] = true;
    else if (ch) _topoPoolSelection.channels[ch] = true;
  }
  _topoPoolPersistSelection();
}
/* Shift-click range-select within a single pool section. Walks sibling
 * chips between the last-clicked anchor and the target; adds the whole
 * inclusive range to the selection (additive so it composes with prior
 * ctrl-click picks). The anchor is tracked per-session only. */
var _topoPoolSelAnchor = null;
function _topoPoolSelectRange(targetChip) {
  if (!targetChip) return;
  var section = targetChip.closest(".topo-pool-section");
  if (!section) return;
  var chips = Array.prototype.slice.call(
    section.querySelectorAll(".topo-pool-chip"),
  );
  var tgtIdx = chips.indexOf(targetChip);
  if (tgtIdx < 0) return;
  var anchorIdx = -1;
  if (_topoPoolSelAnchor) {
    for (var i = 0; i < chips.length; i++) {
      var c = chips[i];
      var ag = c.getAttribute("data-agent");
      var ch = c.getAttribute("data-channel");
      if (
        (_topoPoolSelAnchor.kind === "agent" &&
          ag === _topoPoolSelAnchor.name) ||
        (_topoPoolSelAnchor.kind === "channel" &&
          ch === _topoPoolSelAnchor.name)
      ) {
        anchorIdx = i;
        break;
      }
    }
  }
  if (anchorIdx < 0) anchorIdx = tgtIdx;
  var lo = Math.min(anchorIdx, tgtIdx);
  var hi = Math.max(anchorIdx, tgtIdx);
  for (var j = lo; j <= hi; j++) {
    var ch2 = chips[j];
    var ag2 = ch2.getAttribute("data-agent");
    var c2 = ch2.getAttribute("data-channel");
    if (ag2) _topoPoolSelection.agents[ag2] = true;
    else if (c2) _topoPoolSelection.channels[c2] = true;
  }
  _topoPoolPersistSelection();
}

/* Save / recall / list memory presets. Slot numbers are 1-based
 * (displayed as M1..M5). Save overwrites; recall replaces the current
 * selection with the slot contents.
 *
 * todo#98 — snapshot structure is {agents, channels, hidden, filter,
 * label, savedAt}. The extended fields are optional so older slots
 * (agents+channels only) still recall correctly. */
function _topoPoolMemorySnapshot() {
  /* Sidebar filter state: raw #filter-input text + parsed activeTags.
   * Raw text captures is:<flag> tokens and free-form search words;
   * activeTags captures the agent/host/channel/label/project chips
   * rendered as pill tokens. Both are needed because the two stores
   * diverge by design (todo#72). */
  var input = null;
  try {
    input = document.getElementById("filter-input");
  } catch (_e) {}
  var rawInput =
    (input && typeof input.value === "string" && input.value) || "";
  var tags = [];
  try {
    if (typeof activeTags !== "undefined" && Array.isArray(activeTags)) {
      for (var i = 0; i < activeTags.length; i++) {
        var t = activeTags[i];
        if (t && typeof t.type === "string" && typeof t.value === "string") {
          tags.push({ type: t.type, value: t.value });
        }
      }
    }
  } catch (_e) {}
  return {
    agents: Object.keys(_topoPoolSelection.agents),
    channels: Object.keys(_topoPoolSelection.channels),
    hidden: {
      agents: Object.keys(_topoHidden.agents || {}),
      channels: Object.keys(_topoHidden.channels || {}),
    },
    filter: { input: rawInput, tags: tags },
    savedAt: Date.now(),
  };
}
function _topoPoolMemorySave(slot) {
  if (!slot || slot < 1 || slot > _TOPO_POOL_MEM_MAX) return;
  /* Preserve existing label on overwrite so users don't lose the name
   * they gave a slot when they refresh its contents. */
  var prev = _topoPoolMemories[String(slot)] || {};
  var snap = _topoPoolMemorySnapshot();
  if (prev.label) snap.label = prev.label;
  _topoPoolMemories[String(slot)] = snap;
  _topoPoolPersistMemories();
}
function _topoPoolMemoryRename(slot, label) {
  var mem = _topoPoolMemories[String(slot)];
  if (!mem) return false;
  if (label && typeof label === "string") {
    mem.label = label.slice(0, 32);
  } else {
    delete mem.label;
  }
  _topoPoolPersistMemories();
  return true;
}
function _topoPoolMemoryRecall(slot) {
  var mem = _topoPoolMemories[String(slot)];
  if (!mem) return false;
  /* Pool selection. */
  _topoPoolSelection = {
    agents: Object.create(null),
    channels: Object.create(null),
  };
  (mem.agents || []).forEach(function (n) {
    _topoPoolSelection.agents[n] = true;
  });
  (mem.channels || []).forEach(function (n) {
    _topoPoolSelection.channels[n] = true;
  });
  _topoPoolPersistSelection();
  /* Hidden set (right-click→Hide). Slots saved before todo#98 lack
   * this field; skip the apply rather than nuke whatever the user
   * currently has hidden. */
  if (mem.hidden && typeof mem.hidden === "object") {
    _topoHidden = { agents: {}, channels: {} };
    (mem.hidden.agents || []).forEach(function (n) {
      _topoHidden.agents[n] = true;
    });
    (mem.hidden.channels || []).forEach(function (n) {
      _topoHidden.channels[n] = true;
    });
    _topoSaveHidden();
    _topoLastSig = "";
  }
  /* Sidebar filter: restore raw input + activeTags, then re-run the
   * global filter + chip sync. Guarded by typeof checks because the
   * sidebar may not be present on every render path. */
  if (mem.filter && typeof mem.filter === "object") {
    try {
      if (typeof activeTags !== "undefined" && Array.isArray(activeTags)) {
        activeTags.length = 0;
        var fTags = mem.filter.tags;
        if (Array.isArray(fTags)) {
          for (var k = 0; k < fTags.length; k++) {
            var ft = fTags[k];
            if (ft && ft.type && typeof ft.value === "string") {
              activeTags.push({ type: ft.type, value: ft.value });
            }
          }
        }
        if (typeof renderTags === "function") renderTags();
        if (typeof syncFilterVisuals === "function") syncFilterVisuals();
      }
    } catch (_e) {}
    try {
      var fi = document.getElementById("filter-input");
      if (fi) {
        fi.value =
          (mem.filter.input &&
            typeof mem.filter.input === "string" &&
            mem.filter.input) ||
          "";
        fi.dispatchEvent(new Event("input", { bubbles: true }));
      }
    } catch (_e) {}
  }
  return true;
}
function _topoPoolMemoryDelete(slot) {
  if (!_topoPoolMemories[String(slot)]) return;
  delete _topoPoolMemories[String(slot)];
  _topoPoolPersistMemories();
}
function _topoPoolMemoryNextFreeSlot() {
  for (var s = 1; s <= _TOPO_POOL_MEM_MAX; s++) {
    if (!_topoPoolMemories[String(s)]) return s;
  }
  return 0;
}
/* Walk the DOM and re-apply .topo-pool-chip-selected to chips that are
 * in the current selection. Called after every selection mutation so
 * the highlight stays in sync without waiting for a full re-render.
 * Also applies the canvas filter (hide non-selected non-neighbor nodes
 * + non-incident edges) when selection is non-empty — todo#79 "Pools
 * as filters". */
function _topoPoolSelectionPaint(root) {
  var host = root || document;
  var chips = host.querySelectorAll(".topo-pool-chip");
  for (var i = 0; i < chips.length; i++) {
    var chip = chips[i];
    var ag = chip.getAttribute("data-agent");
    var ch = chip.getAttribute("data-channel");
    var sel = ag
      ? !!_topoPoolSelection.agents[ag]
      : !!(ch && _topoPoolSelection.channels[ch]);
    chip.classList.toggle("topo-pool-chip-selected", sel);
  }
  /* Update the memory-strip counter + memory button filled state so
   * the UI reflects current selection size / occupied slots. */
  var counter = host.querySelector(".topo-pool-selcount");
  if (counter) {
    var n = _topoPoolSelectionSize();
    counter.textContent = n === 0 ? "" : n + " selected";
  }
  var memBtns = host.querySelectorAll(".topo-pool-mem-btn[data-mem-slot]");
  for (var m = 0; m < memBtns.length; m++) {
    var slot = memBtns[m].getAttribute("data-mem-slot");
    var slotN = parseInt(slot, 10);
    memBtns[m].classList.toggle(
      "topo-pool-mem-btn-filled",
      !!_topoPoolMemories[slot],
    );
    /* Highlight the active slot so users see which Mn is recording. */
    memBtns[m].classList.toggle(
      "topo-pool-mem-btn-active",
      _topoActiveMemSlot === slotN,
    );
    /* Dirty dot — active slot whose saved snapshot diverges from the
     * current selection. User spec 2026-04-20: "no auto-save" + small
     * unsaved indicator so users know which slot needs a Save click. */
    var dirty = _topoActiveMemSlot === slotN && _topoPoolMemoryIsDirty(slotN);
    memBtns[m].classList.toggle("topo-pool-mem-btn-dirty", dirty);
    if (dirty) {
      memBtns[m].setAttribute(
        "data-dirty-title",
        "Unsaved changes — click Save to persist",
      );
    } else {
      memBtns[m].removeAttribute("data-dirty-title");
    }
  }
  _topoPoolApplyCanvasFilter(host);
  /* Sidebar Memory section mirrors pool chip state — keep both in
   * lockstep. Sidebar renderer lives in app/sidebar-memory.js. */
  if (typeof _syncMemoryDirtyIndicators === "function") {
    _syncMemoryDirtyIndicators();
  }
}
/* Cross-surface sync: both pool chips AND the sidebar Memory section
 * render memory slot buttons and a Save/unsaved indicator. This helper
 * walks EVERY matching chip (ignoring which DOM subtree hosts it) and
 * reconciles the filled/active/dirty classes + data-dirty-title. Called
 * from _topoPoolSelectionPaint above and from sidebar-memory.js after
 * its own renders. */
function _syncMemoryDirtyIndicators() {
  var all = document.querySelectorAll(
    ".topo-pool-mem-btn[data-mem-slot], .sidebar-mem-btn[data-mem-slot]",
  );
  for (var i = 0; i < all.length; i++) {
    var btn = all[i];
    var slot = btn.getAttribute("data-mem-slot");
    var slotN = parseInt(slot, 10);
    btn.classList.toggle("topo-pool-mem-btn-filled", !!_topoPoolMemories[slot]);
    btn.classList.toggle("sidebar-mem-btn-filled", !!_topoPoolMemories[slot]);
    btn.classList.toggle(
      "topo-pool-mem-btn-active",
      _topoActiveMemSlot === slotN,
    );
    btn.classList.toggle(
      "sidebar-mem-btn-active",
      _topoActiveMemSlot === slotN,
    );
    var dirty = _topoActiveMemSlot === slotN && _topoPoolMemoryIsDirty(slotN);
    btn.classList.toggle("topo-pool-mem-btn-dirty", dirty);
    btn.classList.toggle("sidebar-mem-btn-dirty", dirty);
    if (dirty) {
      btn.setAttribute(
        "data-dirty-title",
        "Unsaved changes — click Save to persist",
      );
    } else {
      btn.removeAttribute("data-dirty-title");
    }
  }
}
window._topoPoolMemoryIsDirty = _topoPoolMemoryIsDirty;
window._syncMemoryDirtyIndicators = _syncMemoryDirtyIndicators;
/* Apply filter classes to SVG canvas nodes + edges. When selection is
 * empty: clear all filter classes (show everything). Non-empty: compute
 * the neighborhood of the selection (a selected agent pulls in all its
 * channels; a selected channel pulls in all its agents), then mark any
 * node / edge not in that neighborhood with .topo-pool-filtered-out so
 * CSS can dim + hide it. Uses only DOM traversal (no re-layout) so the
 * canvas zoom / pan state is preserved. */
function _topoPoolApplyCanvasFilter(root) {
  var host = root || document;
  var svg = host.querySelector(".topo-svg");
  if (!svg) return;
  var selA = _topoPoolSelection.agents;
  var selC = _topoPoolSelection.channels;
  var selSize = Object.keys(selA).length + Object.keys(selC).length;
  var agents = svg.querySelectorAll(".topo-agent[data-agent]");
  var channels = svg.querySelectorAll(".topo-channel[data-channel]");
  var edges = svg.querySelectorAll(
    ".topo-edge[data-agent][data-channel], .topo-edge-hit[data-agent][data-channel]",
  );
  if (selSize === 0) {
    for (var a0 = 0; a0 < agents.length; a0++) {
      agents[a0].classList.remove("topo-pool-filtered-out");
    }
    for (var c0 = 0; c0 < channels.length; c0++) {
      channels[c0].classList.remove("topo-pool-filtered-out");
    }
    for (var e0 = 0; e0 < edges.length; e0++) {
      edges[e0].classList.remove("topo-pool-filtered-out");
    }
    svg.classList.remove("topo-svg-pool-filtered");
    return;
  }
  /* Compute the neighborhood: selected entities + all direct neighbors
   * reachable through a subscribed edge. We derive neighbors from edge
   * endpoints already in the DOM so we don't need the agent/channel
   * data orochi_model here. */
  var keepA = Object.create(null);
  var keepC = Object.create(null);
  Object.keys(selA).forEach(function (n) {
    keepA[n] = true;
  });
  Object.keys(selC).forEach(function (n) {
    keepC[n] = true;
  });
  for (var ei = 0; ei < edges.length; ei++) {
    var ed = edges[ei];
    var eAg = ed.getAttribute("data-agent");
    var eCh = ed.getAttribute("data-channel");
    if (!eAg || !eCh) continue;
    if (selA[eAg]) keepC[eCh] = true;
    if (selC[eCh]) keepA[eAg] = true;
  }
  /* Apply visibility classes */
  for (var ai = 0; ai < agents.length; ai++) {
    var an = agents[ai].getAttribute("data-agent");
    agents[ai].classList.toggle("topo-pool-filtered-out", !keepA[an]);
  }
  for (var ci = 0; ci < channels.length; ci++) {
    var cn = channels[ci].getAttribute("data-channel");
    channels[ci].classList.toggle("topo-pool-filtered-out", !keepC[cn]);
  }
  for (var gi = 0; gi < edges.length; gi++) {
    var g = edges[gi];
    var gAg = g.getAttribute("data-agent");
    var gCh = g.getAttribute("data-channel");
    /* Edge stays only if BOTH endpoints survive AND at least one end is
     * actually in the selection (so neighbor↔neighbor edges don't leak
     * in — we want the star-graph around the selection, not its full
     * subgraph). */
    var inSel = selA[gAg] || selC[gCh];
    var visible = keepA[gAg] && keepC[gCh] && inSel;
    g.classList.toggle("topo-pool-filtered-out", !visible);
  }
  svg.classList.add("topo-svg-pool-filtered");
}
