/* composer/composer-paste.js — paste + drag/drop handlers for the SSoT
 * composer. Mirror of composer-paste.ts. Exposes globals for classic
 * script consumers and also re-uses upload.js's _pastedTextShouldAttach
 * / _buildPastedTextFile when available. */
/* globals: _pastedTextShouldAttach, _buildPastedTextFile */

(function () {
  function _collectPastedImages(cd) {
    var collected = [];
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

  function wireComposerPaste(input, stageFiles, opts) {
    var stop = opts && opts.stopPropagation !== false;
    function handler(ev) {
      if (stop) ev.stopPropagation();
      var cd =
        ev.clipboardData ||
        (ev.originalEvent && ev.originalEvent.clipboardData);
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

  function wireComposerDragDrop(host, stageFiles, opts) {
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

  window._composerCollectPastedImages = _collectPastedImages;
  window.wireComposerPaste = wireComposerPaste;
  window.wireComposerDragDrop = wireComposerDragDrop;
})();
