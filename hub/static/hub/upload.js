/* File upload -- attach, drag-drop, clipboard paste (multi-file) */
/* globals: currentChannel, userName, sendOrochiMessage, token, apiUrl, csrfToken */

(function () {
  /* Make the file input multi-select */
  var fileInput = document.getElementById("file-input");
  if (fileInput && !fileInput.hasAttribute("multiple")) {
    fileInput.setAttribute("multiple", "multiple");
  }
})();

document.getElementById("msg-attach").addEventListener("click", function () {
  document.getElementById("file-input").click();
});

document
  .getElementById("file-input")
  .addEventListener("change", async function () {
    if (!this.files || this.files.length === 0) return;
    var arr = Array.prototype.slice.call(this.files);
    await uploadFiles(arr);
    this.value = "";
  });

/**
 * Upload one or more files in a single POST and emit ONE message that
 * carries all attachments. Used by the file picker, drag-drop, and
 * clipboard paste — all paths converge here.
 */
async function uploadFiles(files) {
  if (!files || files.length === 0) return;
  console.log("[orochi-upload] uploadFiles called:", files.length, "files");
  var formData = new FormData();
  files.forEach(function (f) {
    formData.append("file", f);
  });
  try {
    var headers = {};
    if (typeof csrfToken !== "undefined" && csrfToken) {
      headers["X-CSRFToken"] = csrfToken;
    }
    var uploadUrl = apiUrl("/api/upload");
    console.log("[orochi-upload] POST to:", uploadUrl);
    var res = await fetch(uploadUrl, {
      method: "POST",
      headers: headers,
      credentials: "same-origin",
      body: formData,
    });
    if (!res.ok) {
      var errText = await res.text();
      console.error("[orochi-upload] Upload failed:", res.status, errText);
      return;
    }
    var result = await res.json();
    console.log("[orochi-upload] Upload result:", result);
    /* Backend returns {files: [...], errors: [...], count, ...top-level-mirror} */
    var attachments = (result && result.files) || (result && result.url ? [result] : []);
    if (attachments.length === 0) {
      console.error("[orochi-upload] no successful uploads", result);
      return;
    }
    var channel = currentChannel || "#general";
    var contentText = attachments.length === 1
      ? attachments[0].filename
      : attachments.length + " files: " + attachments.map(function (a) { return a.filename; }).join(", ");
    sendOrochiMessage({
      type: "message",
      sender: userName,
      payload: {
        channel: channel,
        content: contentText,
        attachments: attachments,
      },
    });
  } catch (e) {
    console.error("[orochi-upload] Upload error:", e);
  }
}

/* Backward-compat single-file wrapper */
async function uploadFile(file) {
  return uploadFiles([file]);
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
    uploadFiles(Array.prototype.slice.call(files));
  }
});

/* Clipboard paste image upload
 *
 * Bound to the message textarea explicitly (not document) so the handler
 * runs in the capture phase for that element and we can preventDefault
 * before the browser inserts anything. Also falls back through files[]
 * and items[] because browsers expose image clipboard data differently.
 */
function handleClipboardPaste(e) {
  var cd = e.clipboardData || (e.originalEvent && e.originalEvent.clipboardData);
  if (!cd) return;
  /* Collect image files from the clipboard.
   *
   * A single paste event can expose the same image via BOTH cd.files and
   * cd.items (getAsFile() returns a fresh File object each time, so
   * reference-equality dedup fails). Prefer cd.files when non-empty and
   * fall back to cd.items only when files is empty. Then dedup by
   * (name, size, type, lastModified) to guard against duplicates from
   * multi-source browsers. */
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
    console.log("[orochi-upload] pasting", collected.length, "image(s) from clipboard");
    uploadFiles(collected);
  }
}
/* Bind ONCE to the textarea — duplicate-binding (also on document) caused
   "image.png shown twice" because both handlers fired for the same event. */
msgInput.addEventListener("paste", handleClipboardPaste);
