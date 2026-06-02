// @ts-nocheck
/* composer/composer-attach.ts — attach-button / camera / sketch / voice
 * wiring for the SSoT composer. Each surface supplies its own file-input
 * element (Chat reuses the static #file-input; Overview + Reply create
 * one inline) plus optional callbacks for webcam / sketch / voice.
 *
 * Delegation targets:
 *   - attach  : click() the provided <input type="file"> element
 *   - camera  : openWebcam() from webcam.ts (global msg-webcam button wire
 *               still exists for the Chat surface; the composer's own
 *               button additionally invokes openWebcam() directly)
 *   - sketch  : openSketch() from sketch.ts. Surfaces can pass an
 *               `onSketchOpen` hook to set a per-surface flag
 *               (threads/panel.ts sets `_threadSketchActive`).
 *   - voice   : window.toggleVoiceInput() from voice-input.ts — but first
 *               focus the composer's textarea so _toggleVoice's target
 *               resolution picks it up. This replaces three identical
 *               copies of the same four-line block (Chat inherits via
 *               voice-input's generic handler; Overview + Reply both had
 *               their own inline copies).
 *
 * `wireAttachButtons(opts)` is a single call the composer makes after
 * it has rendered its action row. Returns a disposer that removes all
 * listeners — used by surfaces that rebuild their composer on open
 * (Overview popup, thread panel). */

import { openSketch } from "../sketch";
import { openWebcam } from "../webcam";

export interface AttachWireOpts {
  input: HTMLTextAreaElement;
  fileInput?: HTMLInputElement | null;
  attachBtn?: HTMLElement | null;
  cameraBtn?: HTMLElement | null;
  sketchBtn?: HTMLElement | null;
  voiceBtn?: HTMLElement | null;
  onAttach?: () => void;
  onCamera?: () => void;
  onSketchOpen?: () => void;
  onVoiceToggle?: () => void;
  /* Consumed by file-input change: each surface stages files into its own
   * attachment store. When omitted, the surface is responsible for binding
   * file-input.change itself. */
  stageFiles?: (files: File[]) => void | Promise<void>;
}

export function wireAttachButtons(opts: AttachWireOpts): () => void {
  var disposers: Array<() => void> = [];

  function bind(el, ev, fn) {
    if (!el) return;
    el.addEventListener(ev, fn);
    disposers.push(function () {
      el.removeEventListener(ev, fn);
    });
  }

  if (opts.attachBtn && opts.fileInput) {
    bind(opts.attachBtn, "click", function () {
      if (typeof opts.onAttach === "function") {
        try {
          opts.onAttach();
        } catch (_) {}
      }
      opts.fileInput.click();
    });
  }

  if (opts.fileInput && typeof opts.stageFiles === "function") {
    bind(opts.fileInput, "change", function () {
      var files = Array.prototype.slice.call(opts.fileInput.files || []);
      opts.stageFiles(files);
      opts.fileInput.value = "";
    });
  }

  if (opts.cameraBtn) {
    bind(opts.cameraBtn, "click", function () {
      if (typeof opts.onCamera === "function") {
        try {
          opts.onCamera();
        } catch (_) {}
      }
      if (typeof openWebcam === "function") {
        try {
          openWebcam();
        } catch (_) {}
      }
    });
  }

  if (opts.sketchBtn) {
    bind(opts.sketchBtn, "click", function () {
      if (typeof opts.onSketchOpen === "function") {
        try {
          opts.onSketchOpen();
        } catch (_) {}
      }
      if (typeof openSketch === "function") {
        try {
          openSketch();
        } catch (_) {}
      }
    });
  }

  if (opts.voiceBtn) {
    bind(opts.voiceBtn, "click", function () {
      /* Focus the textarea first so voice-input.ts's _toggleVoice target
       * resolution picks this composer's input (critical for Overview /
       * Reply surfaces where the Chat msg-input would otherwise win). */
      try {
        opts.input && opts.input.focus();
      } catch (_) {}
      if (typeof opts.onVoiceToggle === "function") {
        try {
          opts.onVoiceToggle();
        } catch (_) {}
        return;
      }
      if (typeof (window as any).toggleVoiceInput === "function") {
        try {
          (window as any).toggleVoiceInput();
        } catch (_) {}
      }
    });
  }

  return function dispose() {
    while (disposers.length) {
      var d = disposers.pop();
      try {
        d();
      } catch (_) {}
    }
  };
}
