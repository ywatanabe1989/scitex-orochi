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
      var res = await fetch(apiUrl("/api/upload"), {
        method: "POST",
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
  var formData = new FormData();
  formData.append("file", file);
  try {
    var res = await fetch(apiUrl("/api/upload"), {
      method: "POST",
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

/* Clipboard paste image upload */
document.addEventListener("paste", function (e) {
  var items = (e.clipboardData || {}).items;
  if (!items) return;
  for (var i = 0; i < items.length; i++) {
    if (items[i].type.indexOf("image/") === 0) {
      e.preventDefault();
      var file = items[i].getAsFile();
      if (file) uploadFile(file);
      return;
    }
  }
});
