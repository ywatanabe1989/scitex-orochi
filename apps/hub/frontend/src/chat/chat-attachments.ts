// @ts-nocheck
import { escapeHtml, timeAgo } from "../app/utils";
import { openImgViewer } from "../files-tab/files-tab-core";
import { openThreadForMessage } from "../threads/panel";

export function appendSystemMessage(msg) {
  var el = document.createElement("div");
  el.className = "msg msg-system";
  var ts = "";
  if (msg.ts) {
    var d = new Date(msg.ts);
    if (!isNaN(d.getTime())) {
      ts = timeAgo(msg.ts);
    }
  }
  var text = msg.text || "";
  el.innerHTML =
    '<div class="msg-system-content">' +
    '<span class="msg-system-icon">\u2022</span> ' +
    '<span class="msg-system-text">' +
    escapeHtml(text) +
    "</span>" +
    (ts ? ' <span class="ts">' + ts + "</span>" : "") +
    "</div>";
  var container = document.getElementById("messages");
  var nearBottom =
    container.scrollHeight - container.scrollTop - container.clientHeight < 150;
  /* Mirror appendMessage's focus/scroll guard — see todo#225/#227. */
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  container.appendChild(el);
  if (nearBottom) {
    container.scrollTop = container.scrollHeight;
  }
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
}

/* Jump to a referenced message by opening its thread panel (msg#9641 / #362).
 * Correct spec per ywatanabe msg#9644: clicking msg#NNNN opens thread panel,
 * does NOT scroll the feed. Falls back to flash-in-place if threads.js
 * not loaded yet. */
export function jumpToMsg(id) {
  if (typeof openThreadForMessage === "function") {
    openThreadForMessage(String(id));
    return;
  }
  /* Fallback: scroll + flash in feed */
  var el = document.querySelector('[data-msg-id="' + id + '"]');
  if (!el) return;
  var container = document.getElementById("messages");
  if (container) {
    var top = el.offsetTop - container.clientHeight / 2 + el.offsetHeight / 2;
    container.scrollTop = Math.max(0, top);
  }
  el.classList.add("msg-highlight");
  setTimeout(function () {
    el.classList.remove("msg-highlight");
  }, 2000);
}

/* Shared attachment renderer — used by both the main feed and thread panel.
 * Returns an HTML string for all attachments in the array. */
export function buildAttachmentsHtml(attachments) {
  var html = "";
  if (!attachments || !attachments.length) return html;
  var imageAttachments = attachments.filter(function (att) {
    return att.mime_type && att.mime_type.startsWith("image/") && att.url;
  });
  var imgCount = imageAttachments.length;
  var gridClass =
    imgCount <= 1
      ? "count-1"
      : imgCount === 2
        ? "count-2"
        : imgCount === 3
          ? "count-3"
          : "count-many";
  var imagesHtml = "";
  imageAttachments.forEach(function (att) {
    imagesHtml +=
      '<div class="attachment-img"><a href="' +
      escapeHtml(att.url) +
      '" target="_blank">' +
      '<img src="' +
      escapeHtml(att.url) +
      '" alt="' +
      escapeHtml(att.filename || "image") +
      '" loading="lazy"></a></div>';
  });
  if (imgCount > 0)
    html +=
      '<div class="attachment-grid ' + gridClass + '">' + imagesHtml + "</div>";
  attachments.forEach(function (att) {
    if (!att.url) return;
    var mime = att.mime_type || "";
    var fname = att.filename || "attachment";
    var url = att.url;
    if (mime.indexOf("image/") === 0) return; /* handled in grid */
    var sizeStr = att.size
      ? att.size > 1024 * 1024
        ? (att.size / 1024 / 1024).toFixed(1) + " MB"
        : (att.size / 1024).toFixed(0) + " KB"
      : "";
    var ext = (fname.split(".").pop() || "").toLowerCase();
    var isMarkdown =
      mime === "text/markdown" || ext === "md" || ext === "markdown";
    var isText =
      mime.indexOf("text/") === 0 ||
      mime === "application/json" ||
      ext === "txt" ||
      ext === "log" ||
      ext === "py" ||
      ext === "json" ||
      ext === "yaml" ||
      ext === "yml" ||
      ext === "toml" ||
      ext === "sh";
    var isPdf = mime === "application/pdf" || ext === "pdf";
    var isVideo = mime.indexOf("video/") === 0;
    var isAudio = mime.indexOf("audio/") === 0;
    if (isVideo) {
      html +=
        '<div class="attachment-video"><video src="' +
        escapeHtml(url) +
        '" controls preload="metadata" style="max-width:100%"></video>' +
        '<div class="attachment-caption">' +
        escapeHtml(fname) +
        (sizeStr ? " · " + escapeHtml(sizeStr) : "") +
        "</div></div>";
      return;
    }
    if (isAudio) {
      html +=
        '<div class="attachment-audio"><audio src="' +
        escapeHtml(url) +
        '" controls preload="metadata" style="max-width:100%"></audio>' +
        '<div class="attachment-caption">' +
        escapeHtml(fname) +
        (sizeStr ? " · " + escapeHtml(sizeStr) : "") +
        "</div></div>";
      return;
    }
    if (isPdf) {
      /* The attachment-card-icon is tagged with data-pdf-thumb-url so
       * pdf-thumbnail.js can swap the "PDF" placeholder for the actual
       * first-page image after async render. todo#89. */
      html +=
        '<div class="attachment-card attachment-card-pdf" onclick="event.preventDefault();event.stopPropagation();' +
        "if(typeof openPdfViewer==='function')openPdfViewer(" +
        JSON.stringify(url).replace(/"/g, "&quot;") +
        "," +
        JSON.stringify(fname).replace(/"/g, "&quot;") +
        ");else window.open(" +
        JSON.stringify(url).replace(/"/g, "&quot;") +
        ",'_blank')\">" +
        '<div class="attachment-card-icon" data-pdf-thumb-url="' +
        escapeHtml(url) +
        '">PDF</div>' +
        '<div class="attachment-card-meta"><div class="attachment-card-name">' +
        escapeHtml(fname) +
        "</div>" +
        (sizeStr
          ? '<div class="attachment-card-size">' +
            escapeHtml(sizeStr) +
            "</div>"
          : "") +
        "</div></div>";
      return;
    }
    if (isMarkdown || isText) {
      var previewId = "att-prev-" + Math.random().toString(36).slice(2, 10);
      html +=
        '<div class="attachment-card attachment-card-text' +
        (isMarkdown ? " attachment-card-md" : "") +
        '">' +
        '<div class="attachment-card-header"><a href="' +
        escapeHtml(url) +
        '" target="_blank" download class="attachment-card-name">' +
        escapeHtml(fname) +
        "</a>" +
        (sizeStr
          ? '<span class="attachment-card-size">' +
            escapeHtml(sizeStr) +
            "</span>"
          : "") +
        "</div>" +
        '<pre class="attachment-card-preview" id="' +
        previewId +
        '">\u2026 loading preview \u2026</pre></div>';
      setTimeout(function () {
        var pre = document.getElementById(previewId);
        if (!pre) return;
        fetch(url, { credentials: "same-origin" })
          .then(function (r) {
            if (!r.ok) throw new Error("preview fetch " + r.status);
            return r.text();
          })
          .then(function (text) {
            var p = document.getElementById(previewId);
            if (!p) return;
            var snippet = (text || "").slice(0, 1200);
            if (text.length > 1200) snippet += "\n\u2026";
            p.textContent = snippet;
          })
          .catch(function (_) {
            var p = document.getElementById(previewId);
            if (p) p.textContent = "(preview unavailable)";
          });
      }, 0);
      return;
    }
    html +=
      '<div class="attachment-file"><a href="' +
      escapeHtml(url) +
      '" target="_blank" download>' +
      "\uD83D\uDCCE " +
      escapeHtml(fname) +
      (sizeStr ? " (" + escapeHtml(sizeStr) + ")" : "") +
      "</a></div>";
  });
  return html;
}

/* Render unprocessed mermaid diagrams within a given root element.
 * Calls mermaid.run() then wraps each rendered SVG as a blob-URL <img>
 * so that right-click Save/Copy works natively (scitex-orochi#165). */
export function _renderMermaidIn(root) {
  if (typeof window.mermaid === "undefined") return;
  var nodes = (root || document).querySelectorAll(
    ".mermaid-rendered:not([data-mermaid-processed])",
  );
  if (!nodes.length) return;
  nodes.forEach(function (n) {
    n.setAttribute("data-mermaid-processed", "1");
  });
  var promise;
  try {
    promise = window.mermaid.run({ nodes: nodes });
  } catch (e) {
    /* Non-fatal: diagram parse error shows in the rendered div */
    return;
  }
  /* After render completes, convert SVG elements to blob-URL <img> tags
   * so that right-click "Save image" / "Copy image" works natively. */
  if (promise && typeof promise.then === "function") {
    promise
      .then(function () {
        nodes.forEach(function (n) {
          _mermaidSvgToImg(n);
        });
      })
      .catch(function () {
        /* parse errors: leave div as-is */
      });
  } else {
    /* Synchronous fallback (older mermaid builds) */
    setTimeout(function () {
      nodes.forEach(function (n) {
        _mermaidSvgToImg(n);
      });
    }, 100);
  }
}

/* Serialize the SVG rendered inside a .mermaid-rendered div to a blob URL,
 * replace the SVG with a responsive <img> (enables native right-click Save/Copy),
 * and wire click-to-enlarge via the existing files-tab lightbox.
 * scitex-orochi#165 */
export function _mermaidSvgToImg(container) {
  var svgEl = container.querySelector("svg");
  if (!svgEl) return; /* parse error — no SVG was produced */

  /* Ensure the SVG namespace is set so XMLSerializer produces valid SVG */
  if (!svgEl.getAttribute("xmlns")) {
    svgEl.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  }

  var svgStr = new XMLSerializer().serializeToString(svgEl);
  var blob = new Blob([svgStr], { type: "image/svg+xml" });
  var url = URL.createObjectURL(blob);

  var img = document.createElement("img");
  img.src = url;
  img.alt = "Mermaid diagram";
  img.className = "mermaid-img";

  /* Replace inline SVG with <img>; blob URL stays alive so right-click Save works */
  svgEl.parentNode.replaceChild(img, svgEl);

  /* Click-to-enlarge: open in the existing image lightbox (files-tab.js openImgViewer) */
  container.addEventListener("click", function (e) {
    if (e.target.closest(".mermaid-toggle")) return;
    if (typeof openImgViewer === "function") {
      openImgViewer(url, "mermaid-diagram.svg", [
        { url: url, filename: "mermaid-diagram.svg" },
      ]);
    }
  });
}
