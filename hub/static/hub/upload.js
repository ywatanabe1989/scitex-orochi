/* File upload -- attach, drag-drop, clipboard paste */
/* globals: currentChannel, userName, sendOrochiMessage, token, apiUrl */

document.getElementById("msg-attach").addEventListener("click", function () {
  document.getElementById("file-input").click();
});

document
  .getElementById("file-input")
  .addEventListener("change", async function () {
    var file = this.files[0];
    if (!file) return;
    var formData = new FormData();
    formData.append("file", file);
    try {
      var headers = {};
      if (csrfToken) headers["X-CSRFToken"] = csrfToken;
      var res = await fetch(apiUrl("/api/upload"), {
        method: "POST",
        headers: headers,
        credentials: "same-origin",
        body: formData,
      });
      if (!res.ok) {
        console.error("Upload failed:", res.status);
        return;
      }
      var result = await res.json();
      var channel = currentChannel || "#general";
      sendOrochiMessage({
        type: "message",
        sender: userName,
        payload: {
          channel: channel,
          content: file.name,
          attachments: [result],
        },
      });
    } catch (e) {
      console.error("Upload error:", e);
    }
    this.value = "";
  });

async function uploadFile(file) {
  console.log("[orochi-upload] uploadFile called:", file.name, file.type, file.size);
  var formData = new FormData();
  formData.append("file", file);
  try {
    var headers = {};
    if (csrfToken) headers["X-CSRFToken"] = csrfToken;
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
    if (!result.url) {
      console.error("[orochi-upload] Response has no url field!", result);
      return;
    }
    var channel = currentChannel || "#general";
    console.log("[orochi-upload] Sending message with attachment, url:", result.url);
    sendOrochiMessage({
      type: "message",
      sender: userName,
      payload: {
        channel: channel,
        content: file.name,
        attachments: [result],
      },
    });
  } catch (e) {
    console.error("[orochi-upload] Upload error:", e);
  }
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
  for (var i = 0; i < files.length; i++) {
    uploadFile(files[i]);
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
  /* Try files[] first (Chrome/Edge for screenshots) */
  var fileList = cd.files;
  if (fileList && fileList.length) {
    for (var i = 0; i < fileList.length; i++) {
      var f = fileList[i];
      if (f && f.type && f.type.indexOf("image/") === 0) {
        e.preventDefault();
        console.log("[orochi-upload] pasting image via files[]:", f.name || "pasted", f.type, f.size);
        uploadFile(f);
        return;
      }
    }
  }
  /* Fallback to items[] (Firefox, Safari) */
  var items = cd.items;
  if (!items) return;
  for (var j = 0; j < items.length; j++) {
    var it = items[j];
    if (it && it.type && it.type.indexOf("image/") === 0) {
      e.preventDefault();
      var file = it.getAsFile();
      if (file) {
        console.log("[orochi-upload] pasting image via items[]:", file.name || "pasted", file.type, file.size);
        uploadFile(file);
      }
      return;
    }
  }
}
msgInput.addEventListener("paste", handleClipboardPaste);
/* Also listen on document as a backup in case focus is elsewhere */
document.addEventListener("paste", handleClipboardPaste);
