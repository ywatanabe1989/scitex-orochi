/* composer/composer-attach.js — mirror of composer-attach.ts. Delegates
 * attach/camera/sketch/voice button wiring. */
/* globals: openSketch, openWebcam */

(function () {
  function wireAttachButtons(opts) {
    var disposers = [];
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
          try { opts.onAttach(); } catch (_) {}
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
          try { opts.onCamera(); } catch (_) {}
        }
        if (typeof openWebcam === "function") {
          try { openWebcam(); } catch (_) {}
        }
      });
    }

    if (opts.sketchBtn) {
      bind(opts.sketchBtn, "click", function () {
        if (typeof opts.onSketchOpen === "function") {
          try { opts.onSketchOpen(); } catch (_) {}
        }
        if (typeof openSketch === "function") {
          try { openSketch(); } catch (_) {}
        }
      });
    }

    if (opts.voiceBtn) {
      bind(opts.voiceBtn, "click", function () {
        try { opts.input && opts.input.focus(); } catch (_) {}
        if (typeof opts.onVoiceToggle === "function") {
          try { opts.onVoiceToggle(); } catch (_) {}
          return;
        }
        if (typeof window.toggleVoiceInput === "function") {
          try { window.toggleVoiceInput(); } catch (_) {}
        }
      });
    }

    return function dispose() {
      while (disposers.length) {
        var d = disposers.pop();
        try { d(); } catch (_) {}
      }
    };
  }

  window.wireAttachButtons = wireAttachButtons;
})();
