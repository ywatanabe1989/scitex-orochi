// @ts-nocheck
/* composer/composer-paste.ts — paste + drag/drop handlers for the SSoT
 * composer. Extracted so the Chat / Overview / Reply composers share one
 * code path instead of three near-duplicates.
 *
 * Each composer surface provides a `stageFiles(files)` callback via opts;
 * this module turns raw paste / drop DOM events into a dedup'd File[] and
 * invokes it. Does NOT know about the surface's pending-attachments tray —
 * that stays with the surface (Chat: module-level pendingAttachments;
 * Overview: popup-local popPending[]; Reply: window.threadPendingAttachments).
 *
 * Text-paste-as-file heuristic (todo#52) lives in upload.ts
 * (_pastedTextShouldAttach / _buildPastedTextFile) and is reused here so
 * every surface behaves identically.
 *
 * Paste-target guard (msg#16193): `_isTargetOnChatTab` is Chat-specific.
 * The per-composer handler knows its own surface, so we don't need the
 * guard here — the handler is bound to the surface's own textarea and
 * stops propagation so the Chat-level msg-input paste handler (which
 * still uses _isTargetOnChatTab as a safety net) won't double-fire. */

import {
  _buildPastedTextFile,
  _pastedTextShouldAttach,
} from "../upload";

export type ComposerPasteStageFn = (files: File[]) => void | Promise<void>;

/* Collect image files from a clipboard DataTransfer, dedup by
 * (name|size|type|lastModified). Mirrors the exact dedup used in the
 * pre-SSoT Chat + Overview paste handlers. */
export function _collectPastedImages(cd): File[] {
  var collected: File[] = [];
  var seen = new Set();
  function pushUnique(f) {
    if (!f || !f.type || f.type.indexOf("image/") !== 0) return;
    var key =
      f.name + "|" + f.size + "|" + f.type + "|" + (f.lastModified || 0);
    if (seen.has(key)) return;
    seen.add(key);
    collected.push(f);
  }
  if (!cd) return collected;
  var fileList = cd.files;
  if (fileList && fileList.length) {
    for (var i = 0; i < fileList.length; i++) pushUnique(fileList[i]);
  } else if (cd.items) {
    for (var j = 0; j < cd.items.length; j++) {
      var it = cd.items[j];
      if (it && it.type && it.type.indexOf("image/") === 0) {
        pushUnique(it.getAsFile());
      }
    }
  }
  return collected;
}

/* Install a paste handler on `input` that stages pasted images + long
 * plain text into the surface's attachment store via `stageFiles`.
 *
 * Returns a disposer that removes the listener. */
export function wireComposerPaste(
  input: HTMLElement,
  stageFiles: ComposerPasteStageFn,
  opts?: { stopPropagation?: boolean },
): () => void {
  var stop = opts && opts.stopPropagation !== false; /* default true */
  function handler(ev) {
    if (stop) ev.stopPropagation();
    var cd =
      ev.clipboardData || (ev.originalEvent && ev.originalEvent.clipboardData);
    if (!cd) return;
    var collected = _collectPastedImages(cd);
    var text = "";
    try {
      text = cd.getData("text/plain") || "";
    } catch (_) {}
    var attachText =
      typeof _pastedTextShouldAttach === "function" &&
      _pastedTextShouldAttach(text);
    if (collected.length > 0 || attachText) {
      ev.preventDefault();
      if (attachText && typeof _buildPastedTextFile === "function") {
        collected.push(_buildPastedTextFile(text));
      }
      stageFiles(collected);
    }
  }
  input.addEventListener("paste", handler);
  return function () {
    input.removeEventListener("paste", handler);
  };
}

/* Install drag-over / drop handlers. `host` is the outer composer
 * element (gets .drag-over class during an active drag); `stageFiles`
 * is called with the dropped File[]. Returns a disposer. */
export function wireComposerDragDrop(
  host: HTMLElement,
  stageFiles: ComposerPasteStageFn,
  opts?: { dragOverClass?: string },
): () => void {
  var cls = (opts && opts.dragOverClass) || "drag-over";
  function onOver(ev) {
    ev.preventDefault();
    ev.stopPropagation();
    host.classList.add(cls);
  }
  function onLeave() {
    host.classList.remove(cls);
  }
  function onDrop(ev) {
    ev.preventDefault();
    ev.stopPropagation();
    host.classList.remove(cls);
    var files = ev.dataTransfer && ev.dataTransfer.files;
    if (files && files.length) {
      stageFiles(Array.prototype.slice.call(files));
    }
  }
  host.addEventListener("dragover", onOver);
  host.addEventListener("dragleave", onLeave);
  host.addEventListener("drop", onDrop);
  return function () {
    host.removeEventListener("dragover", onOver);
    host.removeEventListener("dragleave", onLeave);
    host.removeEventListener("drop", onDrop);
  };
}
