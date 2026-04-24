// @ts-nocheck
/* composer/draft-store.ts — localStorage-backed per-surface draft
 * persistence for message composers.
 *
 * msg#16324 (ywatanabe) / worker-progress msg#16325: when the user is
 * typing in any compose surface (Chat, Overview popup, thread reply)
 * and the site reloads — deploy, Cmd-R, unintentional nav — the typed
 * content vanishes. This module persists the in-progress text to
 * localStorage, scoped by (surface, target), so a subsequent mount of
 * the same composer on the same channel/target can restore it.
 *
 * Key format:
 *   orochi.draft.<surface>.<target>
 * Value format (JSON):
 *   { text: string, savedAt: ISO8601 string }
 *
 * Design notes:
 *   - localStorage (not sessionStorage) so drafts survive tab close.
 *   - 24h stale cutoff: older drafts aren't restored and are garbage-
 *     collected on app boot via cleanupStaleDrafts().
 *   - Every localStorage call is wrapped in try/catch because private
 *     mode and quota-exceeded scenarios throw synchronously.
 *   - Save is debounced at 300ms by the CALLERS (via _debounceSave
 *     below) so we don't churn localStorage on every keystroke. The
 *     debounce uses requestIdleCallback when available so it never
 *     competes with keystroke repaint.
 *
 * Interaction with the parallel composer SSoT refactor
 * (feat/composer-ssot-unification): this module is intentionally
 * self-contained and side-effect-free at import time. The SSoT PR will
 * re-expose these helpers as composer options; until then each surface
 * wires them independently with a minimal diff.
 */

const KEY_PREFIX = "orochi.draft.";
const STALE_MS = 24 * 60 * 60 * 1000; // 24 hours

export function _draftKey(surface: string, target: string): string {
  /* Empty target is valid (e.g. no channel selected yet) — we still
   * need a stable key so a draft typed at that moment can be restored
   * later. Fall back to "__default__" the way the pre-existing
   * sessionStorage draft did. */
  const t = target == null || target === "" ? "__default__" : String(target);
  return KEY_PREFIX + String(surface) + "." + t;
}

export function saveDraft(surface: string, target: string, text: string): void {
  if (typeof localStorage === "undefined") return;
  const key = _draftKey(surface, target);
  try {
    if (text && text.length > 0) {
      const payload = JSON.stringify({
        text: String(text),
        savedAt: new Date().toISOString(),
      });
      localStorage.setItem(key, payload);
    } else {
      /* Empty text → treat as "no draft" and remove the key so a stale
       * value doesn't linger and get restored next mount. */
      localStorage.removeItem(key);
    }
  } catch (_) {
    /* private mode, quota, or corrupted storage — silent. */
  }
}

export function loadDraft(surface: string, target: string): string | null {
  if (typeof localStorage === "undefined") return null;
  const key = _draftKey(surface, target);
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(key);
  } catch (_) {
    return null;
  }
  if (!raw) return null;
  let parsed: any;
  try {
    parsed = JSON.parse(raw);
  } catch (_) {
    /* Legacy or corrupted entry — drop it so we don't keep trying. */
    try {
      localStorage.removeItem(key);
    } catch (__) {}
    return null;
  }
  if (!parsed || typeof parsed.text !== "string") return null;
  const savedAt = parsed.savedAt ? Date.parse(parsed.savedAt) : NaN;
  if (!isFinite(savedAt)) return null;
  if (Date.now() - savedAt > STALE_MS) {
    /* Stale — drop it and report no draft. */
    try {
      localStorage.removeItem(key);
    } catch (_) {}
    return null;
  }
  return parsed.text;
}

export function clearDraft(surface: string, target: string): void {
  if (typeof localStorage === "undefined") return;
  const key = _draftKey(surface, target);
  try {
    localStorage.removeItem(key);
  } catch (_) {}
}

export function cleanupStaleDrafts(): void {
  if (typeof localStorage === "undefined") return;
  const now = Date.now();
  /* Collect keys first — mutating localStorage while iterating by index
   * can skip entries because subsequent keys shift down. */
  const toCheck: string[] = [];
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.indexOf(KEY_PREFIX) === 0) toCheck.push(k);
    }
  } catch (_) {
    return;
  }
  for (const k of toCheck) {
    try {
      const raw = localStorage.getItem(k);
      if (!raw) continue;
      let parsed: any;
      try {
        parsed = JSON.parse(raw);
      } catch (_) {
        /* Corrupted — remove it. */
        localStorage.removeItem(k);
        continue;
      }
      const savedAt = parsed && parsed.savedAt ? Date.parse(parsed.savedAt) : NaN;
      if (!isFinite(savedAt) || now - savedAt > STALE_MS) {
        localStorage.removeItem(k);
      }
    } catch (_) {
      /* keep going — one bad key shouldn't abort the sweep */
    }
  }
}

/* Per-(surface,target) debounced save. Callers wire an input listener
 * that calls _debounceSave(surface, target, text). The debounce is
 * 300ms; we schedule via requestIdleCallback when available so the
 * write never blocks keystroke repaint, falling back to setTimeout.
 *
 * Each pending entry stashes the latest (surface, target, text) so
 * flushPendingSaves() can drain them synchronously — needed on channel
 * switch to guarantee the previous channel's final keystrokes hit
 * storage before we hydrate the new channel's draft. */
const _pending: Record<string, any> = {};
const DEBOUNCE_MS = 300;

export function _debounceSave(surface: string, target: string, text: string): void {
  const key = _draftKey(surface, target);
  const prev = _pending[key];
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
  const doSave = () => {
    delete _pending[key];
    saveDraft(surface, target, text);
  };
  if (
    typeof requestIdleCallback === "function" &&
    typeof cancelIdleCallback === "function"
  ) {
    /* `timeout` ensures the save happens within the 300ms budget even
     * when the main thread stays busy. */
    const handle = requestIdleCallback(doSave, { timeout: DEBOUNCE_MS });
    _pending[key] = { kind: "idle", handle, surface, target, text };
  } else {
    const handle = setTimeout(doSave, DEBOUNCE_MS);
    _pending[key] = { kind: "timeout", handle, surface, target, text };
  }
}

/* Synchronously flush every pending debounced save. Call this before a
 * context switch (channel change, popup close) so no in-flight keystroke
 * is lost when we hydrate a different target into the same textarea. */
export function flushPendingSaves(): void {
  const keys = Object.keys(_pending);
  for (const key of keys) {
    const p = _pending[key];
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

/* Expose to window for the hand-maintained JS mirror and for quick
 * console-based debugging (e.g. `orochiDraftStore.loadDraft('chat',
 * '#proj-neurovista')`). */
try {
  (globalThis as any).orochiDraftStore = {
    saveDraft,
    loadDraft,
    clearDraft,
    cleanupStaleDrafts,
    flushPendingSaves,
    _debounceSave,
    _draftKey,
  };
} catch (_) {}
