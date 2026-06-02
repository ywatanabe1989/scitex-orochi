// @ts-nocheck
import { apiUrl, cleanAgentName, escapeHtml, getAgentColor, timeAgo } from "../app/utils";
import { filesMatchQuery, filesSelected, filesSetPreviewIdx, filesSetView, filesViewMode, formatFileSize, matchesFilter, mimeCategory, renderFilePreview } from "./files-tab-core";
import { runFilter } from "../filter/runner";

/* Files tab — grid render, selection, fetch, init, PDF modal viewer */
/* globals: apiUrl, escapeHtml, timeAgo, getAgentColor, cleanAgentName */

export function renderFilesGrid() {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var grid = document.getElementById("files-grid");
  if (!grid) return;
  var items = (globalThis as any).filesCache.filter(function (i) {
    return matchesFilter(i) && filesMatchQuery(i);
  });
  /* Build image list for lightbox navigation */
  (globalThis as any).imgViewerImages = items
    .filter(function (i) {
      return mimeCategory(i.mime_type) === "image";
    })
    .map(function (i) {
      return { url: i.url, filename: i.filename };
    });
  if (items.length === 0) {
    grid.innerHTML =
      '<p class="empty-notice">No files yet. Upload via the chat input (attach, drag, or paste).</p>';
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try {
        msgInput.setSelectionRange(savedStart, savedEnd);
      } catch (_) {}
    }
    return;
  }
  /* Rebuild selected set using cache indices (filter may have changed) */
  var selectedHtml =
    filesSelected.size > 0
      ? '<div class="files-selection-bar">' +
        "<span>" +
        filesSelected.size +
        " file" +
        (filesSelected.size !== 1 ? "s" : "") +
        " selected</span>" +
        '<button type="button" class="files-dl-btn" onclick="filesDownloadSelected()">Download selected</button>' +
        '<button type="button" class="files-clear-btn" onclick="filesClearSelection()">Clear</button>' +
        "</div>"
      : "";

  function _catIcon(cat) {
    return cat === "image"
      ? "🖼"
      : cat === "application/pdf"
        ? "📄"
        : cat === "video"
          ? "🎬"
          : cat === "audio"
            ? "🎵"
            : "📁";
  }

  if (filesViewMode === "tiles") {
    grid.className = "files-tiles";
    grid.innerHTML =
      selectedHtml +
      items
        .map(function (item) {
          var cacheIdx = (globalThis as any).filesCache.indexOf(item);
          var isSelected = filesSelected.has(cacheIdx);
          var cat = mimeCategory(item.mime_type);
          var senderColor = getAgentColor(item.sender);
          var thumb =
            cat === "image"
              ? '<img class="files-tile-thumb" src="' +
                escapeHtml(item.url) +
                '" alt="" loading="lazy">'
              : cat === "application/pdf"
                ? '<div class="files-tile-icon" data-pdf-thumb-url="' +
                  escapeHtml(item.url) +
                  '">' +
                  _catIcon(cat) +
                  "</div>"
                : '<div class="files-tile-icon">' + _catIcon(cat) + "</div>";
          return (
            '<div class="files-tile' +
            (isSelected ? " file-card-selected" : "") +
            '"' +
            ' onclick="filesHandleClick(event,' +
            cacheIdx +
            ')">' +
            thumb +
            '<div class="files-tile-body">' +
            '<div class="files-tile-name">' +
            escapeHtml(item.filename || "file") +
            "</div>" +
            '<div class="files-tile-meta">' +
            escapeHtml(item.mime_type || "") +
            (item.size
              ? " &middot; " + escapeHtml(formatFileSize(item.size))
              : "") +
            "</div>" +
            '<div class="files-tile-sub" style="color:' +
            senderColor +
            '">' +
            escapeHtml(cleanAgentName(item.sender)) +
            " &middot; " +
            escapeHtml(timeAgo(item.ts) || "") +
            "</div>" +
            "</div>" +
            "</div>"
          );
        })
        .join("");
    if (window.pdfThumb) window.pdfThumb.hydrateAll(grid);
    return;
  }

  if (filesViewMode === "list" || filesViewMode === "details") {
    /* List: name + basic cols. Details: adds channel column and uses wider layout. */
    var isDetails = filesViewMode === "details";
    grid.className = "files-list" + (isDetails ? " files-list-details" : "");
    grid.innerHTML =
      selectedHtml +
      '<table class="files-list-table"><thead><tr>' +
      "<th></th><th>Name</th><th>Type</th><th>Size</th><th>Sender</th>" +
      (isDetails ? "<th>Channel</th>" : "") +
      "<th>When</th>" +
      "</tr></thead><tbody>" +
      items
        .map(function (item) {
          var cacheIdx = (globalThis as any).filesCache.indexOf(item);
          var isSelected = filesSelected.has(cacheIdx);
          var cat = mimeCategory(item.mime_type);
          var icon =
            cat === "image"
              ? "🖼"
              : cat === "application/pdf"
                ? "📄"
                : cat === "video"
                  ? "🎬"
                  : cat === "audio"
                    ? "🎵"
                    : "📁";
          var senderColor = getAgentColor(item.sender);
          return (
            '<tr class="files-list-row' +
            (isSelected ? " file-card-selected" : "") +
            '" onclick="filesHandleClick(event,' +
            cacheIdx +
            ')">' +
            '<td class="flt-icon">' +
            icon +
            "</td>" +
            '<td class="flt-name"><a href="' +
            escapeHtml(item.url) +
            '" download onclick="event.stopPropagation()" target="_blank">' +
            escapeHtml(item.filename || "file") +
            "</a></td>" +
            '<td class="flt-mime">' +
            escapeHtml(
              (item.mime_type || "").split("/")[1] || item.mime_type || "",
            ) +
            "</td>" +
            '<td class="flt-size">' +
            escapeHtml(formatFileSize(item.size)) +
            "</td>" +
            '<td class="flt-sender" style="color:' +
            senderColor +
            '">' +
            escapeHtml(cleanAgentName(item.sender)) +
            "</td>" +
            (isDetails
              ? '<td class="flt-channel">' +
                escapeHtml(item.channel || "") +
                "</td>"
              : "") +
            '<td class="flt-when">' +
            escapeHtml(timeAgo(item.ts) || "") +
            "</td>" +
            "</tr>"
          );
        })
        .join("") +
      "</tbody></table>";
    return;
  }

  grid.className = "files-grid";
  grid.innerHTML =
    selectedHtml +
    items
      .map(function (item, _idx) {
        /* find real index in (globalThis as any).filesCache for stable selection tracking */
        var cacheIdx = (globalThis as any).filesCache.indexOf(item);
        var isSelected = filesSelected.has(cacheIdx);
        var senderColor = getAgentColor(item.sender);
        var when = timeAgo(item.ts) || "";
        var sizeStr = formatFileSize(item.size);
        var meta = [];
        if (item.channel) meta.push(escapeHtml(item.channel));
        if (sizeStr) meta.push(escapeHtml(sizeStr));
        if (item.mime_type) meta.push(escapeHtml(item.mime_type));
        /* For images: open lightbox on plain click */
        var isImg = mimeCategory(item.mime_type) === "image";
        var imgClickAttr = isImg
          ? 'onclick="event.preventDefault();event.stopPropagation();openImgViewer(' +
            JSON.stringify(item.url) +
            "," +
            JSON.stringify(item.filename || "") +
            ',(globalThis as any).imgViewerImages)"'
          : "";
        var previewHtml = isImg
          ? '<a href="' +
            escapeHtml(item.url) +
            '" class="file-preview-link" ' +
            imgClickAttr +
            ">" +
            '<img class="file-preview-img" src="' +
            escapeHtml(item.url) +
            '" alt="' +
            escapeHtml(item.filename || "") +
            '" loading="lazy">' +
            "</a>"
          : renderFilePreview(item);
        return (
          '<div class="file-card' +
          (isSelected ? " file-card-selected" : "") +
          '" ' +
          'data-cache-idx="' +
          cacheIdx +
          '" ' +
          'onclick="filesHandleClick(event, ' +
          cacheIdx +
          ')">' +
          (isSelected ? '<div class="file-check-badge">✓</div>' : "") +
          '<div class="file-preview">' +
          previewHtml +
          "</div>" +
          '<div class="file-info">' +
          '<div class="file-name">' +
          '<a href="' +
          escapeHtml(item.url) +
          '" target="_blank" download ' +
          'onclick="event.stopPropagation()">' +
          escapeHtml(item.filename || "file") +
          "</a>" +
          "</div>" +
          '<div class="file-meta">' +
          '<span class="file-sender" style="color:' +
          senderColor +
          '">' +
          escapeHtml(cleanAgentName(item.sender)) +
          "</span>" +
          " &middot; " +
          escapeHtml(when) +
          "</div>" +
          '<div class="file-meta-small">' +
          meta.join(" &middot; ") +
          "</div>" +
          "</div>" +
          "</div>"
        );
      })
      .join("");

  /* Add click delegate for selection */
  grid.addEventListener(
    "click",
    function handler(e) {
      /* handled per-card via filesHandleClick inline */
      grid.removeEventListener("click", handler);
    },
    { once: true },
  );
  /* Re-apply Ctrl+K fuzzy filter after innerHTML rewrite (see todo-tab.js). */
  if (typeof runFilter === "function") runFilter();
  /* Hydrate PDF thumbnails for grid view (todo#89). */
  if (window.pdfThumb) window.pdfThumb.hydrateAll(grid);
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
}

export function filesHandleClick(event, cacheIdx) {
  /* Always update preview-pane selection when a card is clicked. */
  filesSetPreviewIdx(cacheIdx);
  /* Ctrl/Cmd+click or touch-hold toggles selection; plain click opens if nothing selected */
  if (
    event.ctrlKey ||
    event.metaKey ||
    event.shiftKey ||
    filesSelected.size > 0
  ) {
    event.preventDefault();
    if (filesSelected.has(cacheIdx)) {
      filesSelected.delete(cacheIdx);
    } else {
      filesSelected.add(cacheIdx);
    }
    renderFilesGrid();
  }
  /* else: let default <a> link or media click proceed */
}

export function filesClearSelection() {
  filesSelected.clear();
  renderFilesGrid();
}

export function filesDownloadSelected() {
  filesSelected.forEach(function (idx) {
    var item = (globalThis as any).filesCache[idx];
    if (!item || !item.url) return;
    var a = document.createElement("a");
    a.href = item.url;
    a.download = item.filename || "file";
    a.target = "_blank";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  });
}

export async function fetchFiles() {
  try {
    var res = await fetch(apiUrl("/api/media/"), {
      credentials: "same-origin",
    });
    if (!res.ok) {
      console.error("fetchFiles failed:", res.status);
      return;
    }
    (globalThis as any).filesCache = await res.json();
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
      buttons.forEach(function (b) {
        b.classList.remove("active");
      });
      btn.classList.add("active");
      (globalThis as any).filesFilterMime = btn.getAttribute("data-mime");
      renderFilesGrid();
    });
  });
  /* Tab click triggers fetch */
  var tabBtn = document.querySelector('[data-tab="files"]');
  if (tabBtn) {
    tabBtn.addEventListener("click", fetchFiles);
  }
  /* Restore saved view mode */
  try {
    var saved = localStorage.getItem("files.viewMode");
    if (saved && ["grid", "tiles", "list", "details"].indexOf(saved) !== -1) {
      filesSetView(saved);
    }
  } catch (_) {}
  /* Ctrl/Cmd+K focuses fuzzy search while on Files tab */
  document.addEventListener("keydown", function (e) {
    var filesView = document.getElementById("files-view");
    if (!filesView || filesView.style.display === "none") return;
    if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
      var input = document.getElementById("files-search");
      if (input) {
        e.preventDefault();
        input.focus();
        input.select();
      }
    }
  });
});

/* PDF modal viewer (todo#240). Mobile Safari has no reliable
 * 'go back' UI when a PDF is opened in the same tab and Orochi is
 * a SPA, so we control the viewer ourselves with an explicit close
 * button + ESC + outside-click + pop-state. */
export function openPdfViewer(url, filename) {
  if (!url) return;
  closePdfViewer();
  var overlay = document.createElement("div");
  overlay.id = "pdf-modal-overlay";
  overlay.className = "pdf-modal-overlay";
  overlay.innerHTML =
    '<div class="pdf-modal-frame">' +
    '<div class="pdf-modal-header">' +
    '<span class="pdf-modal-title">' +
    (typeof escapeHtml === "function"
      ? escapeHtml(filename || "PDF")
      : filename || "PDF") +
    "</span>" +
    '<a class="pdf-modal-download" href="' +
    url +
    '" download target="_blank" rel="noopener" title="Open in new tab / download">↗</a>' +
    '<button type="button" class="pdf-modal-close" aria-label="Close PDF" ' +
    'onclick="closePdfViewer()">×</button>' +
    "</div>" +
    '<iframe class="pdf-modal-iframe" src="' +
    url +
    '#toolbar=1&navpanes=0" allow="fullscreen"></iframe>' +
    "</div>";
  /* Click on the dim outside the frame closes too */
  overlay.addEventListener("click", function (e) {
    if (e.target === overlay) closePdfViewer();
  });
  document.body.appendChild(overlay);
  document.addEventListener("keydown", _pdfModalEscHandler);
  /* Push history state so the device back button also closes */
  try {
    history.pushState({ pdfModal: true }, "", window.location.href);
  } catch (_) {}
  window.addEventListener("popstate", _pdfModalPopstateHandler);
}

export function closePdfViewer() {
  var overlay = document.getElementById("pdf-modal-overlay");
  if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
  document.removeEventListener("keydown", _pdfModalEscHandler);
  window.removeEventListener("popstate", _pdfModalPopstateHandler);
}

export function _pdfModalEscHandler(e) {
  if (e.key === "Escape") closePdfViewer();
}
export function _pdfModalPopstateHandler(_e) {
  closePdfViewer();
}

window.openPdfViewer = openPdfViewer;
window.closePdfViewer = closePdfViewer;
