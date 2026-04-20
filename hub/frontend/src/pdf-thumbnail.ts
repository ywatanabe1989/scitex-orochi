// @ts-nocheck
// Migrated classic-script file. Types intentionally loose during
// the big-bang JS-to-TS bundle migration. Narrow later, per-file.
/* PDF thumbnail renderer — lazily loads pdf.js from CDN and renders the
 * first page of a PDF to a data-URL image. Used by Files tab and chat
 * attachment renderer so PDFs show a first-page preview instead of a
 * generic icon. todo#89.
 *
 * Usage:
 *   // Render into a generic icon placeholder element:
 *   pdfThumb.hydrate(element, url);
 *   // Or: pdfThumb.render(url).then(dataUrl => ...);
 *
 * The helper:
 *   - Loads pdf.min.js + its worker lazily on first use (once per page)
 *   - Caches results per-URL in a module-level Map (first-page render
 *     is ~50ms-200ms depending on PDF size, so avoiding re-renders
 *     during scroll/re-render is significant)
 *   - Marks target elements with data-pdf-thumb="pending|done|error"
 *     so repeat hydrations no-op
 */

(function (global) {
  "use strict";

  var PDFJS_VERSION = "3.11.174"; /* pinned for cache-friendliness */
  var CDN_BASE =
    "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/" + PDFJS_VERSION;
  var LIB_URL = CDN_BASE + "/pdf.min.js";
  var WORKER_URL = CDN_BASE + "/pdf.worker.min.js";

  var loadPromise = null;
  var cache = new Map(); /* url -> Promise<dataURL> */

  function loadLib() {
    if (loadPromise) return loadPromise;
    if (global.pdfjsLib) {
      try {
        global.pdfjsLib.GlobalWorkerOptions.workerSrc = WORKER_URL;
      } catch (_) {}
      loadPromise = Promise.resolve(global.pdfjsLib);
      return loadPromise;
    }
    loadPromise = new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = LIB_URL;
      s.async = true;
      s.onload = function () {
        if (!global.pdfjsLib) {
          reject(new Error("pdfjsLib missing after load"));
          return;
        }
        try {
          global.pdfjsLib.GlobalWorkerOptions.workerSrc = WORKER_URL;
        } catch (_) {}
        resolve(global.pdfjsLib);
      };
      s.onerror = function () {
        reject(new Error("failed to load pdf.js from " + LIB_URL));
      };
      document.head.appendChild(s);
    });
    return loadPromise;
  }

  /* Render page 1 of `pdfUrl` to a data-URL PNG.
   * Thumbnail size: 128x160 portrait (at the page's intrinsic aspect
   * ratio it fits inside). For landscape PDFs the canvas auto-sizes by
   * aspect — we pick the scale so the longest side is ~160px. */
  function render(pdfUrl, opts) {
    opts = opts || {};
    var maxSide = opts.maxSide || 160;
    if (cache.has(pdfUrl)) return cache.get(pdfUrl);
    var p = loadLib()
      .then(function (pdfjsLib) {
        return pdfjsLib.getDocument({ url: pdfUrl, disableRange: false })
          .promise;
      })
      .then(function (pdf) {
        return pdf.getPage(1);
      })
      .then(function (page) {
        var baseViewport = page.getViewport({ scale: 1 });
        var scale = maxSide / Math.max(baseViewport.width, baseViewport.height);
        var viewport = page.getViewport({ scale: scale });
        var canvas = document.createElement("canvas");
        canvas.width = Math.ceil(viewport.width);
        canvas.height = Math.ceil(viewport.height);
        var ctx = canvas.getContext("2d");
        return page
          .render({ canvasContext: ctx, viewport: viewport })
          .promise.then(function () {
            return canvas.toDataURL("image/png");
          });
      })
      .catch(function (err) {
        /* Remove from cache so a later attempt may retry */
        cache.delete(pdfUrl);
        throw err;
      });
    cache.set(pdfUrl, p);
    return p;
  }

  /* Replace the content of an existing placeholder element (e.g. a
   * <div class="file-icon-pdf">PDF</div>) with an <img> showing the
   * first-page thumbnail. Idempotent — safe to call on re-renders. */
  function hydrate(el, pdfUrl, opts) {
    if (!el || !pdfUrl) return;
    if (el.getAttribute("data-pdf-thumb") === "done") return;
    if (el.getAttribute("data-pdf-thumb") === "pending") return;
    el.setAttribute("data-pdf-thumb", "pending");
    render(pdfUrl, opts)
      .then(function (dataUrl) {
        if (!el.isConnected) return;
        el.setAttribute("data-pdf-thumb", "done");
        /* Replace inner content with the thumbnail image while keeping
         * the host element's layout box. */
        el.innerHTML = "";
        var img = document.createElement("img");
        img.src = dataUrl;
        img.alt = "PDF preview";
        img.className = "pdf-thumb-img";
        img.style.maxWidth = "100%";
        img.style.maxHeight = "100%";
        img.style.objectFit = "contain";
        img.style.display = "block";
        el.appendChild(img);
      })
      .catch(function (err) {
        if (!el.isConnected) return;
        el.setAttribute("data-pdf-thumb", "error");
        /* leave original fallback content as-is */
        if (global.console && console.warn) {
          console.warn("pdf-thumb failed for", pdfUrl, err);
        }
      });
  }

  /* Scan the document for elements tagged [data-pdf-thumb-url] that
   * haven't been hydrated yet. Called after DOM rewrites. */
  function hydrateAll(root) {
    root = root || document;
    var nodes = root.querySelectorAll(
      "[data-pdf-thumb-url]:not([data-pdf-thumb='done']):not([data-pdf-thumb='pending'])",
    );
    nodes.forEach(function (n) {
      var url = n.getAttribute("data-pdf-thumb-url");
      if (url) hydrate(n, url);
    });
  }

  global.pdfThumb = {
    render: render,
    hydrate: hydrate,
    hydrateAll: hydrateAll,
  };
})(window);
