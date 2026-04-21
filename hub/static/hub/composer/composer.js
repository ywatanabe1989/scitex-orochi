/* composer/composer.js — Single-Source-of-Truth message composer.
 * Mirror of composer.ts.
 *
 * renderComposer(host, opts): { root, input, destroy, focus, setValue,
 * getValue }. See composer.ts for the full architectural comment.
 */
/* globals: wireComposerPaste, wireComposerDragDrop, wireComposerMention,
   isMentionDropdownOpen, wireAttachButtons */

(function () {
  var DEFAULT_FEATURES = {
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

  function _buildComposerDom(opts) {
    var features = Object.assign({}, DEFAULT_FEATURES, opts.features || {});
    var root = document.createElement("div");
    root.className = "composer composer-surface-" + opts.surface;
    root.setAttribute("data-composer-surface", opts.surface);

    var input = document.createElement("textarea");
    input.className = "composer-input";
    if (opts.surface === "reply") input.id = "thread-input";
    input.setAttribute("data-voice-input", "");
    input.setAttribute("rows", "2");
    input.placeholder = opts.placeholder || "Type a message…";
    input.autocomplete = "off";

    var fileInput = null;
    if (features.attach) {
      fileInput = document.createElement("input");
      fileInput.type = "file";
      fileInput.multiple = true;
      fileInput.style.display = "none";
      fileInput.className = "composer-file-input";
      if (opts.surface === "reply") fileInput.id = "thread-file-input";
    }

    var actions = document.createElement("div");
    actions.className = "composer-actions";

    var attachBtn = null,
      cameraBtn = null,
      sketchBtn = null,
      voiceBtn = null,
      voiceLangBtn = null,
      sendBtn = null;

    function mkBtn(cls, id, title, emoji) {
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
      cameraBtn = mkBtn(
        "composer-btn-camera",
        null,
        "Take photo",
        "\uD83D\uDCF7",
      );
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

  function _adoptComposerDom(opts) {
    var root = opts.adoptRoot;
    var sel = opts.adoptSelectors || {};
    function q(selector) {
      if (!selector) return null;
      return root.querySelector(selector) || document.querySelector(selector);
    }
    return {
      root: root,
      input: q(sel.input),
      sendBtn: q(sel.sendBtn),
      attachBtn: q(sel.attachBtn),
      cameraBtn: q(sel.cameraBtn),
      sketchBtn: q(sel.sketchBtn),
      voiceBtn: q(sel.voiceBtn),
      voiceLangBtn: q(sel.voiceLangBtn),
      fileInput: q(sel.fileInput),
    };
  }

  function renderComposer(host, opts) {
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

    try {
      built.root.setAttribute("data-composer-surface", opts.surface);
    } catch (_) {}

    if (!opts.adoptRoot && host && built.root.parentNode !== host) {
      host.appendChild(built.root);
    }

    var disposers = [];

    var maxPx =
      typeof opts.maxResizePx === "number"
        ? opts.maxResizePx
        : opts.surface === "reply"
          ? 120
          : 200;
    if (features.autoResize && maxPx > 0) {
      var resize = function () {
        try {
          built.input.style.height = "auto";
          built.input.style.height =
            Math.min(built.input.scrollHeight, maxPx) + "px";
        } catch (_) {}
      };
      built.input.addEventListener("input", resize);
      disposers.push(function () {
        built.input.removeEventListener("input", resize);
      });
    }

    if (features.mention) {
      try {
        wireComposerMention(built.input);
      } catch (_) {}
    }

    if (features.paste && typeof opts.stageFiles === "function") {
      disposers.push(wireComposerPaste(built.input, opts.stageFiles));
    }

    if (features.dragDrop && typeof opts.stageFiles === "function") {
      disposers.push(wireComposerDragDrop(built.root, opts.stageFiles));
    }

    if (
      features.attach ||
      features.camera ||
      features.sketch ||
      features.voice
    ) {
      disposers.push(
        wireAttachButtons({
          input: built.input,
          fileInput: built.fileInput,
          attachBtn: features.attach ? built.attachBtn : null,
          cameraBtn: features.camera ? built.cameraBtn : null,
          sketchBtn: features.sketch ? built.sketchBtn : null,
          voiceBtn: features.voice ? built.voiceBtn : null,
          onSketchOpen: opts.onSketchOpen,
          onVoiceToggle: opts.onVoiceToggle,
          stageFiles: opts.stageFiles,
        }),
      );
    }

    function onKeydown(ev) {
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
      if ((ev.ctrlKey || ev.altKey) && features.localVoiceChord !== false) {
        ev.preventDefault();
        ev.stopPropagation();
        try { built.input.focus(); } catch (_) {}
        if (typeof opts.onVoiceToggle === "function") {
          try { opts.onVoiceToggle(); } catch (_) {}
        } else if (typeof window.toggleVoiceInput === "function") {
          try { window.toggleVoiceInput(); } catch (_) {}
        }
        return;
      }
      if (ev.ctrlKey || ev.altKey) return;
      if (features.mention && typeof isMentionDropdownOpen === "function" && isMentionDropdownOpen()) return;
      if (features.shiftEnterNewline !== false && ev.shiftKey) return;
      ev.preventDefault();
      _submit();
    }
    built.input.addEventListener("keydown", onKeydown);
    disposers.push(function () {
      built.input.removeEventListener("keydown", onKeydown);
    });

    function onSendClick(ev) {
      ev.preventDefault();
      _submit();
      try { built.input.focus(); } catch (_) {}
    }
    if (features.sendButton && built.sendBtn) {
      built.sendBtn.addEventListener("click", onSendClick);
      disposers.push(function () {
        built.sendBtn.removeEventListener("click", onSendClick);
      });
    }

    function _submit() {
      var text = built.input.value || "";
      try {
        opts.onSubmit({ text: text });
      } catch (e) {
        console.error("[composer] onSubmit error:", e);
      }
      if (typeof opts.onAfterSubmit === "function") {
        try { opts.onAfterSubmit(); } catch (_) {}
      }
    }

    return {
      root: built.root,
      input: built.input,
      destroy: function () {
        while (disposers.length) {
          var d = disposers.pop();
          try { d(); } catch (_) {}
        }
        if (!opts.adoptRoot && built.root.parentNode) {
          built.root.parentNode.removeChild(built.root);
        }
      },
      focus: function () {
        try { built.input.focus(); } catch (_) {}
      },
      setValue: function (text) {
        built.input.value = text || "";
        built.input.dispatchEvent(new Event("input", { bubbles: true }));
      },
      getValue: function () {
        return built.input.value || "";
      },
    };
  }

  window.renderComposer = renderComposer;
})();
