// @ts-nocheck
/* composer/composer.ts — Single-Source-of-Truth message composer.
 *
 * Three surfaces consume this module:
 *
 *   1. Chat tab composer   (surface: "chat")
 *      Host DOM already exists in dashboard.html (`.input-bar`); we
 *      adopt it rather than re-render, so all historic IDs
 *      (#msg-input, #msg-send, #msg-attach, #msg-webcam, #msg-sketch,
 *      #msg-voice, #msg-voice-lang, #file-input, #pending-attachments)
 *      keep working for voice-input.ts, upload.ts, and every other
 *      module that still talks to those IDs.
 *
 *   2. Overview graph-compose popup  (surface: "overview")
 *      Rendered on-demand anchored near a channel node. The existing
 *      DOM uses tcc-* classes with a textarea; we create the markup
 *      here and keep those classes for CSS compatibility.
 *
 *   3. Reply composer inside the thread panel  (surface: "reply")
 *      Built when the thread panel opens. DOM used to be inlined in
 *      threads/panel.ts; now rendered by renderComposer with a
 *      surface-specific layout class.
 *
 * `renderComposer(host, opts)` returns a `ComposerInstance` with
 * focus / setValue / getValue / destroy — the thin public API.
 * Feature flags live on `opts.features`; each surface toggles the
 * sub-features it wants, so Chat stays fully-featured and the smaller
 * surfaces opt into paste / mention / attach / voice without code
 * duplication. See PR body for the parity matrix.
 */

import {
  wireComposerDragDrop,
  wireComposerPaste,
  type ComposerPasteStageFn,
} from "./composer-paste";
import {
  isMentionDropdownOpen,
  wireComposerMention,
} from "./composer-mention";
import {
  wireAttachButtons,
  type AttachWireOpts,
} from "./composer-attach";

export type ComposerSurface = "chat" | "overview" | "reply";

export interface ComposerSubmitPayload {
  text: string;
  /* Pending attachments are OWNED by the surface (its store); this
   * callback is a pure event — the surface is responsible for
   * clearing its own store afterwards. */
}

export interface ComposerFeatures {
  /* @agent / @user autocomplete (#mention-dropdown) */
  mention?: boolean;
  /* Cmd+V / Ctrl+V paste of images + long plain text */
  paste?: boolean;
  /* Drag-and-drop files onto the composer host */
  dragDrop?: boolean;
  /* 📎 attach button + hidden <input type="file"> */
  attach?: boolean;
  /* 📷 camera button → openWebcam() */
  camera?: boolean;
  /* ✏️ sketch button → openSketch() */
  sketch?: boolean;
  /* 🎤 voice button → window.toggleVoiceInput() */
  voice?: boolean;
  /* Send button visible in the action row */
  sendButton?: boolean;
  /* Cmd+Enter submits. Plain Enter also submits unless shiftEnterNewline
   * is true AND the user held Shift. */
  cmdEnterSubmit?: boolean;
  /* Shift+Enter = newline (default true). When false, plain Enter
   * submits unconditionally and Shift+Enter is a no-op. */
  shiftEnterNewline?: boolean;
  /* Auto-resize textarea up to maxHeight px (0 = no auto-resize). */
  autoResize?: boolean;
  /* Only active on the Chat tab? Guards `activeTab === "chat"` for
   * tab-aware focus. Reply/Overview leave this false. */
  tabAwareFocus?: boolean;
  /* Alt/Ctrl+Enter toggles voice *locally* via the composer's keydown.
   * Default: true — Overview + Reply need this because voice-input.ts's
   * global chord handler explicitly skips those surfaces. Chat leaves it
   * false: voice-input.ts fires on Chat via the global handler, and
   * letting the composer also fire would double-toggle. */
  localVoiceChord?: boolean;
}

export interface ComposerOpts {
  surface: ComposerSurface;
  /* Called when the user presses Enter / Cmd+Enter / clicks Send.
   * Surface packages its own attachment list into the WS/REST payload. */
  onSubmit: (p: ComposerSubmitPayload) => void;
  /* Pass-through stage-files callback — paste / drop / file-picker all
   * funnel through it so the surface keeps ownership of its pending
   * attachments (Chat: upload.ts stageFiles; Overview: popup-local
   * _stagePopFiles; Reply: _stageThreadFiles). */
  stageFiles?: (files: File[]) => void | Promise<void>;
  placeholder?: string;
  features?: ComposerFeatures;
  /* Auto-resize ceiling (default 200 for Chat, 120 for Reply, 0 for
   * Overview's fixed-height popup textarea). */
  maxResizePx?: number;
  /* Chat-only: called on submit success so chat-composer can clear
   * drafts / voice-input state. Not part of the parity contract. */
  onAfterSubmit?: () => void;
  /* Hooks that surfaces can plug into without owning the DOM */
  onSketchOpen?: () => void;
  onVoiceToggle?: () => void;
  /* Which existing element (if any) should be adopted as the
   * composer's root. When omitted, renderComposer creates a new
   * .composer element inside `host`. Chat passes the existing
   * `.input-bar` element so the static dashboard.html DOM is reused. */
  adoptRoot?: HTMLElement;
  /* When adoptRoot is supplied, the composer will lookup its
   * children by these selectors instead of creating new ones.
   * Any missing selector falls back to feature disable. */
  adoptSelectors?: {
    input?: string;
    sendBtn?: string;
    attachBtn?: string;
    cameraBtn?: string;
    sketchBtn?: string;
    voiceBtn?: string;
    voiceLangBtn?: string;
    fileInput?: string;
  };
}

export interface ComposerInstance {
  root: HTMLElement;
  input: HTMLTextAreaElement;
  destroy: () => void;
  focus: () => void;
  setValue: (text: string) => void;
  getValue: () => string;
}

const DEFAULT_FEATURES: ComposerFeatures = {
  mention: true,
  paste: true,
  dragDrop: true,
  attach: true,
  camera: true,
  sketch: true,
  voice: true,
  sendButton: true,
  cmdEnterSubmit: true,
  shiftEnterNewline: true,
  autoResize: true,
  tabAwareFocus: false,
  localVoiceChord: true,
};

/* Build a fresh composer DOM. Used by Overview + Reply surfaces; Chat
 * adopts the static dashboard.html markup via `adoptRoot`. */
function _buildComposerDom(opts: ComposerOpts): {
  root: HTMLElement;
  input: HTMLTextAreaElement;
  sendBtn: HTMLElement | null;
  attachBtn: HTMLElement | null;
  cameraBtn: HTMLElement | null;
  sketchBtn: HTMLElement | null;
  voiceBtn: HTMLElement | null;
  voiceLangBtn: HTMLElement | null;
  fileInput: HTMLInputElement | null;
} {
  var features = Object.assign({}, DEFAULT_FEATURES, opts.features || {});
  var root = document.createElement("div");
  root.className = "composer composer-surface-" + opts.surface;
  root.setAttribute("data-composer-surface", opts.surface);

  var input = document.createElement("textarea");
  input.className = "composer-input";
  if (opts.surface === "reply") {
    input.id = "thread-input";
  }
  input.setAttribute("data-voice-input", "");
  input.setAttribute("rows", "2");
  input.placeholder = opts.placeholder || "Type a message…";
  input.autocomplete = "off";

  var fileInput: HTMLInputElement | null = null;
  if (features.attach) {
    fileInput = document.createElement("input") as HTMLInputElement;
    fileInput.type = "file";
    fileInput.multiple = true;
    fileInput.style.display = "none";
    fileInput.className = "composer-file-input";
    if (opts.surface === "reply") {
      fileInput.id = "thread-file-input";
    }
  }

  var actions = document.createElement("div");
  actions.className = "composer-actions";

  var attachBtn: HTMLElement | null = null;
  var cameraBtn: HTMLElement | null = null;
  var sketchBtn: HTMLElement | null = null;
  var voiceBtn: HTMLElement | null = null;
  var voiceLangBtn: HTMLElement | null = null;
  var sendBtn: HTMLElement | null = null;

  function mkBtn(cls: string, id: string | null, title: string, emoji: string) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "composer-btn " + cls;
    if (id) b.id = id;
    b.tabIndex = -1;
    b.title = title;
    b.setAttribute("aria-label", title);
    b.textContent = emoji;
    return b;
  }

  if (features.attach) {
    attachBtn = mkBtn(
      "composer-btn-attach",
      opts.surface === "reply" ? "thread-attach-btn" : null,
      "Attach file",
      "\uD83D\uDCCE",
    );
    actions.appendChild(attachBtn);
  }
  if (features.camera) {
    cameraBtn = mkBtn("composer-btn-camera", null, "Take photo", "\uD83D\uDCF7");
    actions.appendChild(cameraBtn);
  }
  if (features.sketch) {
    sketchBtn = mkBtn(
      "composer-btn-sketch",
      opts.surface === "reply" ? "thread-sketch-btn" : null,
      "Draw sketch",
      "\u270F\uFE0F",
    );
    actions.appendChild(sketchBtn);
  }
  if (features.voice) {
    voiceBtn = mkBtn(
      "composer-btn-voice",
      opts.surface === "reply" ? "thread-voice-btn" : null,
      "Voice input",
      "\uD83C\uDFA4",
    );
    actions.appendChild(voiceBtn);
    if (opts.surface === "reply") {
      voiceLangBtn = mkBtn(
        "composer-btn-voice-lang",
        "thread-voice-lang-btn",
        "Switch language (EN/JA)",
        "EN",
      );
      voiceLangBtn.style.fontSize = "11px";
      voiceLangBtn.style.padding = "2px 5px";
      voiceLangBtn.style.opacity = "0.7";
      actions.appendChild(voiceLangBtn);
    }
  }
  if (features.sendButton) {
    sendBtn = document.createElement("button");
    sendBtn.type = "button";
    sendBtn.className =
      "composer-btn composer-btn-send " +
      (opts.surface === "reply" ? "thread-send-btn" : "");
    sendBtn.textContent = "Send";
    sendBtn.title = "Send message";
  }

  root.appendChild(input);
  if (fileInput) root.appendChild(fileInput);
  root.appendChild(actions);
  if (sendBtn) actions.appendChild(sendBtn);

  return {
    root: root,
    input: input,
    sendBtn: sendBtn,
    attachBtn: attachBtn,
    cameraBtn: cameraBtn,
    sketchBtn: sketchBtn,
    voiceBtn: voiceBtn,
    voiceLangBtn: voiceLangBtn,
    fileInput: fileInput,
  };
}

function _adoptComposerDom(opts: ComposerOpts) {
  var root = opts.adoptRoot!;
  var sel = opts.adoptSelectors || {};
  function q(selector: string | undefined): any {
    if (!selector) return null;
    return root.querySelector(selector) || document.querySelector(selector);
  }
  return {
    root: root,
    input: q(sel.input) as HTMLTextAreaElement,
    sendBtn: q(sel.sendBtn) as HTMLElement | null,
    attachBtn: q(sel.attachBtn) as HTMLElement | null,
    cameraBtn: q(sel.cameraBtn) as HTMLElement | null,
    sketchBtn: q(sel.sketchBtn) as HTMLElement | null,
    voiceBtn: q(sel.voiceBtn) as HTMLElement | null,
    voiceLangBtn: q(sel.voiceLangBtn) as HTMLElement | null,
    fileInput: q(sel.fileInput) as HTMLInputElement | null,
  };
}

export function renderComposer(
  host: HTMLElement,
  opts: ComposerOpts,
): ComposerInstance {
  if (!opts || typeof opts.onSubmit !== "function") {
    throw new Error("renderComposer: opts.onSubmit is required");
  }
  var features = Object.assign({}, DEFAULT_FEATURES, opts.features || {});
  var built = opts.adoptRoot
    ? _adoptComposerDom(opts)
    : _buildComposerDom(opts);

  if (!built.input) {
    throw new Error(
      "renderComposer: no textarea found for surface " + opts.surface,
    );
  }

  /* Always tag the root with the surface attribute so CSS selectors and
   * debugging queries work uniformly across constructed + adopted DOMs. */
  try {
    built.root.setAttribute("data-composer-surface", opts.surface);
  } catch (_) {}

  /* Mount into host if we built fresh DOM. */
  if (!opts.adoptRoot && host && built.root.parentNode !== host) {
    host.appendChild(built.root);
  }

  var disposers: Array<() => void> = [];

  /* Auto-resize */
  var maxPx =
    typeof opts.maxResizePx === "number"
      ? opts.maxResizePx
      : opts.surface === "reply"
        ? 120
        : 200;
  if (features.autoResize && maxPx > 0) {
    function resize() {
      try {
        (built.input as HTMLTextAreaElement).style.height = "auto";
        (built.input as HTMLTextAreaElement).style.height =
          Math.min(built.input.scrollHeight, maxPx) + "px";
      } catch (_) {}
    }
    built.input.addEventListener("input", resize);
    disposers.push(function () {
      built.input.removeEventListener("input", resize);
    });
  }

  /* Mention autocomplete */
  if (features.mention) {
    try {
      wireComposerMention(built.input);
    } catch (_) {}
  }

  /* Paste */
  if (features.paste && typeof opts.stageFiles === "function") {
    var pasteDispose = wireComposerPaste(built.input, opts.stageFiles);
    disposers.push(pasteDispose);
  }

  /* Drag-drop */
  if (features.dragDrop && typeof opts.stageFiles === "function") {
    var dropDispose = wireComposerDragDrop(built.root, opts.stageFiles);
    disposers.push(dropDispose);
  }

  /* Attach / camera / sketch / voice buttons */
  if (
    features.attach ||
    features.camera ||
    features.sketch ||
    features.voice
  ) {
    var attachOpts: AttachWireOpts = {
      input: built.input as HTMLTextAreaElement,
      fileInput: built.fileInput,
      attachBtn: features.attach ? built.attachBtn : null,
      cameraBtn: features.camera ? built.cameraBtn : null,
      sketchBtn: features.sketch ? built.sketchBtn : null,
      voiceBtn: features.voice ? built.voiceBtn : null,
      onSketchOpen: opts.onSketchOpen,
      onVoiceToggle: opts.onVoiceToggle,
      stageFiles: opts.stageFiles,
    };
    disposers.push(wireAttachButtons(attachOpts));
  }

  /* Keyboard shortcuts: Enter to submit, Shift+Enter for newline, Ctrl+U
   * opens the file picker if one is wired. Alt/Ctrl+Enter is reserved for
   * voice-input on all surfaces — composer just preventDefaults + delegates
   * to the surface's onVoiceToggle hook (or window.toggleVoiceInput). */
  function submitFromKeyboard(ev) {
    ev.preventDefault();
    _submit();
  }
  function onKeydown(ev) {
    /* Cmd/Ctrl+U = file picker (msg#9877) */
    var isMac = /Mac|iPhone|iPad/.test(
      navigator.platform || navigator.userAgent,
    );
    if ((isMac ? ev.metaKey : ev.ctrlKey) && ev.key === "u") {
      if (built.fileInput) {
        ev.preventDefault();
        built.fileInput.click();
      }
      return;
    }
    if (ev.key !== "Enter") return;
    /* Voice toggle chords — Ctrl+Enter / Alt+Enter. Stop propagation so
     * the global voice handler doesn't also fire. Only active when the
     * surface opts into local voice handling; Chat defers to the
     * voice-input.ts global handler to avoid double-toggle. */
    if ((ev.ctrlKey || ev.altKey) && features.localVoiceChord !== false) {
      ev.preventDefault();
      ev.stopPropagation();
      try {
        built.input.focus();
      } catch (_) {}
      if (typeof opts.onVoiceToggle === "function") {
        try {
          opts.onVoiceToggle();
        } catch (_) {}
      } else if (typeof (window as any).toggleVoiceInput === "function") {
        try {
          (window as any).toggleVoiceInput();
        } catch (_) {}
      }
      return;
    }
    /* Even when localVoiceChord is off, Alt+Enter / Ctrl+Enter should
     * not fall through to submit — they belong to the voice-input.ts
     * global chord. Bail before the submit branch. */
    if (ev.ctrlKey || ev.altKey) {
      return;
    }
    /* Don't submit while the mention dropdown is showing a selection. */
    if (features.mention && isMentionDropdownOpen()) return;
    if (features.shiftEnterNewline !== false && ev.shiftKey) {
      return; /* newline */
    }
    submitFromKeyboard(ev);
  }
  built.input.addEventListener("keydown", onKeydown);
  disposers.push(function () {
    built.input.removeEventListener("keydown", onKeydown);
  });

  /* Send button */
  function onSendClick(ev) {
    ev.preventDefault();
    _submit();
    try {
      built.input.focus();
    } catch (_) {}
  }
  if (features.sendButton && built.sendBtn) {
    built.sendBtn.addEventListener("click", onSendClick);
    disposers.push(function () {
      built.sendBtn!.removeEventListener("click", onSendClick);
    });
  }

  function _submit() {
    var text = (built.input as HTMLTextAreaElement).value || "";
    try {
      opts.onSubmit({ text: text });
    } catch (e) {
      console.error("[composer] onSubmit error:", e);
    }
    if (typeof opts.onAfterSubmit === "function") {
      try {
        opts.onAfterSubmit();
      } catch (_) {}
    }
  }

  var instance: ComposerInstance = {
    root: built.root,
    input: built.input as HTMLTextAreaElement,
    destroy: function () {
      while (disposers.length) {
        var d = disposers.pop();
        try {
          d!();
        } catch (_) {}
      }
      /* Only remove DOM we created. Adopted DOM stays in place for the
       * next mount / static page lifecycle. */
      if (!opts.adoptRoot && built.root.parentNode) {
        built.root.parentNode.removeChild(built.root);
      }
    },
    focus: function () {
      try {
        built.input.focus();
      } catch (_) {}
    },
    setValue: function (text) {
      (built.input as HTMLTextAreaElement).value = text || "";
      /* Manually trigger resize since we set value programmatically. */
      built.input.dispatchEvent(new Event("input", { bubbles: true }));
    },
    getValue: function () {
      return (built.input as HTMLTextAreaElement).value || "";
    },
  };

  return instance;
}
