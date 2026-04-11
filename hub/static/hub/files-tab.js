/* Files tab — lists uploaded media with rendering */
/* globals: apiUrl, escapeHtml, timeAgo, getAgentColor, cleanAgentName */

var filesCache = [];
var filesFilterMime = "all";

function formatFileSize(bytes) {
  if (!bytes) return "";
  if (bytes > 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + " MB";
  if (bytes > 1024) return (bytes / 1024).toFixed(0) + " KB";
  return bytes + " B";
}

function mimeCategory(mime) {
  if (!mime) return "other";
  if (mime.indexOf("image/") === 0) return "image";
  if (mime.indexOf("video/") === 0) return "video";
  if (mime.indexOf("audio/") === 0) return "audio";
  if (mime === "application/pdf") return "application/pdf";
  return "other";
}

function matchesFilter(item) {
  if (filesFilterMime === "all") return true;
  var cat = mimeCategory(item.mime_type);
  return cat === filesFilterMime;
}

function renderFilePreview(item) {
  var url = escapeHtml(item.url);
  var filename = escapeHtml(item.filename || "file");
  var cat = mimeCategory(item.mime_type);
  if (cat === "image") {
    return (
      '<a href="' + url + '" target="_blank" class="file-preview-link">' +
      '<img class="file-preview-img" src="' + url + '" alt="' + filename + '" loading="lazy">' +
      '</a>'
    );
  }
  if (cat === "video") {
    return (
      '<video class="file-preview-video" src="' + url + '" controls preload="metadata"></video>'
    );
  }
  if (cat === "audio") {
    return (
      '<audio class="file-preview-audio" src="' + url + '" controls preload="metadata"></audio>'
    );
  }
  if (cat === "application/pdf") {
    return (
      '<a href="' + url + '" target="_blank" class="file-preview-link">' +
      '<div class="file-icon-pdf">PDF</div>' +
      '</a>'
    );
  }
  return (
    '<a href="' + url + '" target="_blank" class="file-preview-link">' +
    '<div class="file-icon-generic">\uD83D\uDCC4</div>' +
    '</a>'
  );
}

function renderFilesGrid() {
  var grid = document.getElementById("files-grid");
  if (!grid) return;
  var items = filesCache.filter(matchesFilter);
  if (items.length === 0) {
    grid.innerHTML = '<p class="empty-notice">No files yet. Upload via the chat input (attach, drag, or paste).</p>';
    return;
  }
  grid.innerHTML = items.map(function (item) {
    var senderColor = getAgentColor(item.sender);
    var when = timeAgo(item.ts) || "";
    var sizeStr = formatFileSize(item.size);
    var meta = [];
    if (item.channel) meta.push(escapeHtml(item.channel));
    if (sizeStr) meta.push(escapeHtml(sizeStr));
    if (item.mime_type) meta.push(escapeHtml(item.mime_type));
    return (
      '<div class="file-card">' +
      '<div class="file-preview">' + renderFilePreview(item) + '</div>' +
      '<div class="file-info">' +
      '<div class="file-name">' +
      '<a href="' + escapeHtml(item.url) + '" target="_blank" download>' +
      escapeHtml(item.filename || "file") +
      '</a>' +
      '</div>' +
      '<div class="file-meta">' +
      '<span class="file-sender" style="color:' + senderColor + '">' +
      escapeHtml(cleanAgentName(item.sender)) +
      '</span>' +
      ' &middot; ' + escapeHtml(when) +
      '</div>' +
      '<div class="file-meta-small">' + meta.join(" &middot; ") + '</div>' +
      '</div>' +
      '</div>'
    );
  }).join("");
}

async function fetchFiles() {
  try {
    var res = await fetch(apiUrl("/api/media/"), { credentials: "same-origin" });
    if (!res.ok) {
      console.error("fetchFiles failed:", res.status);
      return;
    }
    filesCache = await res.json();
    renderFilesGrid();
  } catch (e) {
    console.warn("fetchFiles error:", e);
  }
}

document.addEventListener("DOMContentLoaded", function () {
  /* Filter button handlers */
  var buttons = document.querySelectorAll(".files-filter-btn");
  buttons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      buttons.forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      filesFilterMime = btn.getAttribute("data-mime");
      renderFilesGrid();
    });
  });
  /* Tab click triggers fetch */
  var tabBtn = document.querySelector('[data-tab="files"]');
  if (tabBtn) {
    tabBtn.addEventListener("click", fetchFiles);
  }
});
