// @ts-nocheck
/* Files tab — core: state, query, preview pane, mime helpers, image viewer */
/* globals: apiUrl, escapeHtml, timeAgo, getAgentColor, cleanAgentName */

var filesCache = [];
var filesFilterMime = "all";
var filesSelected = new Set(); /* indices into filesCache of selected items */
var filesViewMode = "grid"; /* "grid" | "tiles" | "list" | "details" */
var filesQuery = "";
var filesPreviewVisible = false;
var filesPreviewIdx = -1;
var imgViewerImages = []; /* [{url, filename}] for current filter set */
var imgViewerIdx = 0;

function filesMatchQuery(item) {
  if (!filesQuery) return true;
  var hay = (
    (item.filename || "") +
    " " +
    (item.mime_type || "") +
    " " +
    (item.sender || "") +
    " " +
    (item.channel || "")
  ).toLowerCase();
  var terms = filesQuery.toLowerCase().split(/\s+/).filter(Boolean);
  for (var i = 0; i < terms.length; i++) {
    if (hay.indexOf(terms[i]) === -1) return false;
  }
  return true;
}

function filesSetQuery(q) {
  filesQuery = q || "";
  renderFilesGrid();
}

function filesTogglePreview() {
  filesPreviewVisible = !filesPreviewVisible;
  var pane = document.getElementById("files-preview-pane");
  var btn = document.getElementById("files-view-preview");
  if (pane) pane.classList.toggle("files-preview-hidden", !filesPreviewVisible);
  if (btn) btn.classList.toggle("active", filesPreviewVisible);
  renderFilesPreview();
}

function filesSetPreviewIdx(cacheIdx) {
  filesPreviewIdx = cacheIdx;
  if (filesPreviewVisible) renderFilesPreview();
}

function renderFilesPreview() {
  var pane = document.getElementById("files-preview-pane");
  if (!pane || !filesPreviewVisible) return;
  var item = filesCache[filesPreviewIdx];
  if (!item) {
    pane.innerHTML = '<div class="files-preview-empty">No file selected</div>';
    return;
  }
  var cat = mimeCategory(item.mime_type);
  var media = "";
  if (cat === "image") {
    media =
      '<img class="files-preview-media" src="' +
      escapeHtml(item.url) +
      '" alt="">';
  } else if (cat === "video") {
    media =
      '<video class="files-preview-media" src="' +
      escapeHtml(item.url) +
      '" controls></video>';
  } else if (cat === "audio") {
    media =
      '<audio class="files-preview-media" src="' +
      escapeHtml(item.url) +
      '" controls></audio>';
  } else if (cat === "application/pdf") {
    media =
      '<iframe class="files-preview-media files-preview-pdf" src="' +
      escapeHtml(item.url) +
      '#toolbar=0&navpanes=0"></iframe>';
  } else {
    media = '<div class="file-icon-generic">\uD83D\uDCC4</div>';
  }
  pane.innerHTML =
    '<div class="files-preview-head">' +
    '<div class="files-preview-name">' +
    escapeHtml(item.filename || "file") +
    "</div>" +
    '<a class="files-preview-open" href="' +
    escapeHtml(item.url) +
    '" target="_blank" download>Open</a>' +
    "</div>" +
    '<div class="files-preview-media-wrap">' +
    media +
    "</div>" +
    '<dl class="files-preview-meta">' +
    "<dt>Type</dt><dd>" +
    escapeHtml(item.mime_type || "-") +
    "</dd>" +
    "<dt>Size</dt><dd>" +
    escapeHtml(formatFileSize(item.size) || "-") +
    "</dd>" +
    '<dt>Sender</dt><dd style="color:' +
    getAgentColor(item.sender) +
    '">' +
    escapeHtml(cleanAgentName(item.sender)) +
    "</dd>" +
    "<dt>Channel</dt><dd>" +
    escapeHtml(item.channel || "-") +
    "</dd>" +
    "<dt>When</dt><dd>" +
    escapeHtml(timeAgo(item.ts) || "-") +
    "</dd>" +
    "</dl>";
}

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
      '<a href="' +
      url +
      '" target="_blank" class="file-preview-link">' +
      '<img class="file-preview-img" src="' +
      url +
      '" alt="' +
      filename +
      '" loading="lazy">' +
      "</a>"
    );
  }
  if (cat === "video") {
    return (
      '<video class="file-preview-video" src="' +
      url +
      '" controls preload="metadata"></video>'
    );
  }
  if (cat === "audio") {
    return (
      '<audio class="file-preview-audio" src="' +
      url +
      '" controls preload="metadata"></audio>'
    );
  }
  if (cat === "application/pdf") {
    /* On mobile Safari `target="_blank"` often opens the PDF inline in
     * the same view with no Orochi chrome and no way back. Force the
     * Orochi-controlled modal viewer instead so the user always has a
     * close button. todo#240, ywatanabe report msg 6073.
     *
     * The inner `.file-icon-pdf` div is tagged with data-pdf-thumb-url
     * so pdfThumb.hydrateAll() swaps the "PDF" text for a first-page
     * image thumbnail after render. todo#89. */
    return (
      '<button type="button" class="file-preview-link file-pdf-open-btn" ' +
      'onclick="event.preventDefault();event.stopPropagation();' +
      "openPdfViewer(" +
      JSON.stringify(url).replace(/"/g, "&quot;") +
      "," +
      JSON.stringify(filename).replace(/"/g, "&quot;") +
      ')">' +
      '<div class="file-icon-pdf" data-pdf-thumb-url="' +
      url +
      '">PDF</div>' +
      "</button>"
    );
  }
  return (
    '<a href="' +
    url +
    '" target="_blank" class="file-preview-link">' +
    '<div class="file-icon-generic">\uD83D\uDCC4</div>' +
    "</a>"
  );
}

function filesSetView(mode) {
  filesViewMode = mode;
  var ids = {
    grid: "files-view-grid",
    tiles: "files-view-tiles",
    list: "files-view-list",
    details: "files-view-details",
  };
  Object.keys(ids).forEach(function (k) {
    var b = document.getElementById(ids[k]);
    if (b) b.classList.toggle("active", mode === k);
  });
  try {
    localStorage.setItem("files.viewMode", mode);
  } catch (_) {}
  renderFilesGrid();
}

function openImgViewer(url, filename, allImages) {
  imgViewerImages = allImages || [{ url: url, filename: filename }];
  imgViewerIdx = imgViewerImages.findIndex(function (i) {
    return i.url === url;
  });
  if (imgViewerIdx < 0) imgViewerIdx = 0;
  _updateImgViewer();
  var ov = document.getElementById("img-viewer-overlay");
  if (ov) ov.style.display = "flex";
  document.addEventListener("keydown", _imgViewerKeyHandler);
}

function closeImgViewer() {
  var ov = document.getElementById("img-viewer-overlay");
  if (ov) ov.style.display = "none";
  document.removeEventListener("keydown", _imgViewerKeyHandler);
}

function imgViewerNav(dir) {
  imgViewerIdx =
    (imgViewerIdx + dir + imgViewerImages.length) % imgViewerImages.length;
  _updateImgViewer();
}

function _updateImgViewer() {
  var item = imgViewerImages[imgViewerIdx];
  if (!item) return;
  var img = document.getElementById("img-viewer-img");
  var cap = document.getElementById("img-viewer-caption");
  var prev = document.getElementById("img-viewer-prev");
  var next = document.getElementById("img-viewer-next");
  if (img) {
    img.src = item.url;
    img.alt = item.filename || "";
  }
  if (cap)
    cap.textContent =
      (item.filename || "") +
      (imgViewerImages.length > 1
        ? " (" + (imgViewerIdx + 1) + "/" + imgViewerImages.length + ")"
        : "");
  if (prev) prev.style.display = imgViewerImages.length > 1 ? "" : "none";
  if (next) next.style.display = imgViewerImages.length > 1 ? "" : "none";
}

function _imgViewerKeyHandler(e) {
  if (e.key === "Escape") {
    closeImgViewer();
    return;
  }
  if (e.key === "ArrowLeft") {
    imgViewerNav(-1);
    return;
  }
  if (e.key === "ArrowRight") {
    imgViewerNav(1);
    return;
  }
}
