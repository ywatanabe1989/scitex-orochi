/* composer/draft-store.js — hand-maintained JS mirror of
 * hub/frontend/src/composer/draft-store.ts. The production bundle
 * is built from the TS source by Vite; this mirror exists so
 * classic-script consumers under hub/static/hub/ stay in sync and
 * so a quick `git grep` across the loose-JS tree surfaces the same
 * behavior. Keep it in lockstep with the .ts file. */

(function () {
  var KEY_PREFIX = "orochi.draft.";
  var STALE_MS = 24 * 60 * 60 * 1000;
  var DEBOUNCE_MS = 300;

  function _draftKey(surface, target) {
    var t = target == null || target === "" ? "__default__" : String(target);
    return KEY_PREFIX + String(surface) + "." + t;
  }

  function saveDraft(surface, target, text) {
    if (typeof localStorage === "undefined") return;
    var key = _draftKey(surface, target);
    try {
      if (text && text.length > 0) {
        var payload = JSON.stringify({
          text: String(text),
          savedAt: new Date().toISOString(),
        });
        localStorage.setItem(key, payload);
      } else {
        localStorage.removeItem(key);
      }
    } catch (_) {}
  }

  function loadDraft(surface, target) {
    if (typeof localStorage === "undefined") return null;
    var key = _draftKey(surface, target);
    var raw = null;
    try {
      raw = localStorage.getItem(key);
    } catch (_) {
      return null;
    }
    if (!raw) return null;
    var parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (_) {
      try {
        localStorage.removeItem(key);
      } catch (__) {}
      return null;
    }
    if (!parsed || typeof parsed.text !== "string") return null;
    var savedAt = parsed.savedAt ? Date.parse(parsed.savedAt) : NaN;
    if (!isFinite(savedAt)) return null;
    if (Date.now() - savedAt > STALE_MS) {
      try {
        localStorage.removeItem(key);
      } catch (_) {}
      return null;
    }
    return parsed.text;
  }

  function clearDraft(surface, target) {
    if (typeof localStorage === "undefined") return;
    var key = _draftKey(surface, target);
    try {
      localStorage.removeItem(key);
    } catch (_) {}
  }

  function cleanupStaleDrafts() {
    if (typeof localStorage === "undefined") return;
    var now = Date.now();
    var toCheck = [];
    try {
      for (var i = 0; i < localStorage.length; i++) {
        var k = localStorage.key(i);
        if (k && k.indexOf(KEY_PREFIX) === 0) toCheck.push(k);
      }
    } catch (_) {
      return;
    }
    for (var j = 0; j < toCheck.length; j++) {
      var key = toCheck[j];
      try {
        var raw = localStorage.getItem(key);
        if (!raw) continue;
        var parsed;
        try {
          parsed = JSON.parse(raw);
        } catch (_) {
          localStorage.removeItem(key);
          continue;
        }
        var savedAt =
          parsed && parsed.savedAt ? Date.parse(parsed.savedAt) : NaN;
        if (!isFinite(savedAt) || now - savedAt > STALE_MS) {
          localStorage.removeItem(key);
        }
      } catch (_) {}
    }
  }

  var _pending = {};
  function _debounceSave(surface, target, text) {
    var key = _draftKey(surface, target);
    var prev = _pending[key];
    if (prev) {
      if (prev.kind === "idle" && typeof cancelIdleCallback === "function") {
        try {
          cancelIdleCallback(prev.handle);
        } catch (_) {}
      } else if (prev.kind === "timeout") {
        clearTimeout(prev.handle);
      }
      delete _pending[key];
    }
    function doSave() {
      delete _pending[key];
      saveDraft(surface, target, text);
    }
    if (
      typeof requestIdleCallback === "function" &&
      typeof cancelIdleCallback === "function"
    ) {
      var handle = requestIdleCallback(doSave, { timeout: DEBOUNCE_MS });
      _pending[key] = {
        kind: "idle",
        handle: handle,
        surface: surface,
        target: target,
        text: text,
      };
    } else {
      var h = setTimeout(doSave, DEBOUNCE_MS);
      _pending[key] = {
        kind: "timeout",
        handle: h,
        surface: surface,
        target: target,
        text: text,
      };
    }
  }

  function flushPendingSaves() {
    var keys = Object.keys(_pending);
    for (var i = 0; i < keys.length; i++) {
      var key = keys[i];
      var p = _pending[key];
      if (!p) continue;
      if (p.kind === "idle" && typeof cancelIdleCallback === "function") {
        try {
          cancelIdleCallback(p.handle);
        } catch (_) {}
      } else if (p.kind === "timeout") {
        clearTimeout(p.handle);
      }
      delete _pending[key];
      try {
        saveDraft(p.surface, p.target, p.text);
      } catch (_) {}
    }
  }

  try {
    window.orochiDraftStore = {
      saveDraft: saveDraft,
      loadDraft: loadDraft,
      clearDraft: clearDraft,
      cleanupStaleDrafts: cleanupStaleDrafts,
      flushPendingSaves: flushPendingSaves,
      _debounceSave: _debounceSave,
      _draftKey: _draftKey,
    };
  } catch (_) {}
})();
