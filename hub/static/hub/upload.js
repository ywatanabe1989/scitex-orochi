/* File upload — attach, drag-drop, clipboard paste (multi-file) with
 * staged preview. Files picked via paste/drag/file-picker are held in a
 * pending tray next to the textarea and only sent when the user presses
 * Send (alongside whatever text they typed). This replaces the old
 * "paste → immediate surprise send" behaviour. */
/* globals: currentChannel, userName, sendOrochiMessage, token, apiUrl, csrfToken */

(function () {
  var fileInput = document.getElementById("file-input");
  if (fileInput && !fileInput.hasAttribute("multiple")) {
    fileInput.setAttribute("multiple", "multiple");
  }
})();

/* Pending attachments (uploaded but not yet sent). Each item:
 *   { file, uploaded: {url, filename, mime_type, size, file_id}, previewEl } */
var pendingAttachments = [];
var _attachmentTray = null;

function _ensureAttachmentTray() {
  if (_attachmentTray) return _attachmentTray;
  var inputBar = document.querySelector(".input-bar");
  if (!inputBar) return null;
  _attachmentTray = document.createElement("div");
  _attachmentTray.id = "pending-attachments";
  _attachmentTray.className = "pending-attachments";
  /* Insert at the very top of .input-bar so the tray floats above whatever
   * row structure the template is using (flat textarea+buttons, or the
   * newer .input-bar-row wrapper). Using insertBefore(textarea) broke
   * because the textarea is no longer a direct child after the layout
   * refactor. */
  if (inputBar.firstChild) {
    inputBar.insertBefore(_attachmentTray, inputBar.firstChild);
  } else {
    inputBar.appendChild(_attachmentTray);
  }
  return _attachmentTray;
}

function _renderAttachmentTray() {
  var tray = _ensureAttachmentTray();
  if (!tray) return;
  if (!pendingAttachments.length) {
    tray.style.display = "none";
    tray.innerHTML = "";
    return;
  }
  tray.style.display = "flex";
  tray.innerHTML = "";
  pendingAttachments.forEach(function (p, idx) {
    var item = document.createElement("div");
    item.className = "pending-attachment";
    var isImage =
      p.uploaded &&
      p.uploaded.mime_type &&
      p.uploaded.mime_type.indexOf("image/") === 0;
    var thumb;
    if (isImage) {
      thumb = document.createElement("img");
      thumb.src = p.uploaded.url;
      thumb.className = "pending-attachment-thumb";
      thumb.alt = p.uploaded.filename || "image";
    } else {
      thumb = document.createElement("span");
      thumb.className = "pending-attachment-icon";
      thumb.textContent = "📎";
    }
    var label = document.createElement("span");
    label.className = "pending-attachment-label";
    label.textContent = (p.uploaded && p.uploaded.filename) || p.file.name;
    var remove = document.createElement("button");
    remove.type = "button";
    remove.className = "pending-attachment-remove";
    remove.title = "Remove";
    remove.textContent = "✕";
    remove.addEventListener("click", function () {
      pendingAttachments.splice(idx, 1);
      _renderAttachmentTray();
    });
    item.appendChild(thumb);
    item.appendChild(label);
    item.appendChild(remove);
    tray.appendChild(item);
  });
}

function clearPendingAttachments() {
  pendingAttachments = [];
  _renderAttachmentTray();
}

function getPendingAttachments() {
  return pendingAttachments.map(function (p) {
    return p.uploaded;
  });
}

document.getElementById("msg-attach").addEventListener("click", function () {
  document.getElementById("file-input").click();
});

document
  .getElementById("file-input")
  .addEventListener("change", async function () {
    if (!this.files || this.files.length === 0) return;
    var arr = Array.prototype.slice.call(this.files);
    await stageFiles(arr);
    this.value = "";
  });

/**
 * Upload one or more files and stage them in the pending tray. Does NOT
 * send a message — that happens when the user presses Send.
 */
async function stageFiles(files) {
  if (!files || files.length === 0) return;
  console.log("[orochi-upload] stageFiles:", files.length);
  var formData = new FormData();
  files.forEach(function (f) {
    formData.append("file", f);
  });
  try {
    var headers = {};
    if (typeof csrfToken !== "undefined" && csrfToken) {
      headers["X-CSRFToken"] = csrfToken;
    }
    var res = await fetch(apiUrl("/api/upload"), {
      method: "POST",
      headers: headers,
      credentials: "same-origin",
      body: formData,
    });
    if (!res.ok) {
      console.error("[orochi-upload] upload failed:", res.status);
      return;
    }
    var result = await res.json();
    var uploaded =
      (result && result.files) || (result && result.url ? [result] : []);
    uploaded.forEach(function (u, i) {
      pendingAttachments.push({ file: files[i] || files[0], uploaded: u });
    });
    _renderAttachmentTray();
  } catch (e) {
    console.error("[orochi-upload] stage error:", e);
  }
}

/* Backward-compat: some older call sites still invoke uploadFile/uploadFiles.
 * Route them through the staging path so behaviour stays consistent. */
async function uploadFile(file) {
  return stageFiles([file]);
}
async function uploadFiles(files) {
  return stageFiles(files);
}

var msgInput = document.getElementById("msg-input");

msgInput.addEventListener("dragover", function (e) {
  e.preventDefault();
  this.classList.add("drag-over");
});
msgInput.addEventListener("dragleave", function () {
  this.classList.remove("drag-over");
});
msgInput.addEventListener("drop", function (e) {
  e.preventDefault();
  this.classList.remove("drag-over");
  var files = e.dataTransfer.files;
  if (files && files.length) {
    stageFiles(Array.prototype.slice.call(files));
  }
});

/* Clipboard paste — stage image(s) in the tray, don't send. Dedup by
 * (name|size|type|lastModified) so the same image can't be captured twice
 * via both cd.files and cd.items on browsers that expose both. */
function handleClipboardPaste(e) {
  var cd = e.clipboardData || (e.originalEvent && e.originalEvent.clipboardData);
  if (!cd) return;
  var collected = [];
  var seen = new Set();
  function pushUnique(f) {
    if (!f || !f.type || f.type.indexOf("image/") !== 0) return;
    var key = f.name + "|" + f.size + "|" + f.type + "|" + (f.lastModified || 0);
    if (seen.has(key)) return;
    seen.add(key);
    collected.push(f);
  }
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
  if (collected.length > 0) {
    e.preventDefault();
    console.log("[orochi-upload] staging", collected.length, "pasted image(s)");
    stageFiles(collected);
  }
}
msgInput.addEventListener("paste", handleClipboardPaste);
