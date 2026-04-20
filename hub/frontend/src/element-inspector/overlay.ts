/**
 * Element Inspector — overlay container + label renderer.
 *
 * Loaded after core.js. Exports OverlayManager and LabelRenderer on
 * `window.__EI`. picker-scanner.js consumes both.
 */
(function () {
  "use strict";

  var EI = (window.__EI = window.__EI || {});

  // ── OverlayManager ───────────────────────────────────────────────
  function OverlayManager() {
    this._container = null;
  }

  OverlayManager.prototype.isActive = function () {
    return this._container !== null;
  };
  OverlayManager.prototype.getContainer = function () {
    return this._container;
  };

  OverlayManager.prototype.createOverlay = function () {
    this._container = document.createElement("div");
    this._container.id = "element-inspector-overlay";
    var docHeight = Math.max(
      document.body.scrollHeight,
      document.documentElement.scrollHeight,
      document.body.offsetHeight,
      document.documentElement.offsetHeight,
      document.body.clientHeight,
      document.documentElement.clientHeight,
    );
    this._container.style.cssText =
      "position:absolute;top:0;left:0;width:100%;height:" +
      docHeight +
      "px;" +
      "pointer-events:none;z-index:999999;";
    document.body.appendChild(this._container);
    return this._container;
  };

  OverlayManager.prototype.removeOverlay = function () {
    if (this._container) {
      this._container.remove();
      this._container = null;
    }
  };

  EI.OverlayManager = OverlayManager;

  // ── LabelRenderer ────────────────────────────────────────────────
  function LabelRenderer(debugCollector, notificationManager) {
    this._debug = debugCollector;
    this._notify = notificationManager;
  }

  LabelRenderer.prototype.shouldShowLabel = function (element, rect, depth) {
    if (element.id) return rect.width > 20 && rect.height > 20;
    if (rect.width > 100 || rect.height > 100) return true;
    var importantTags = [
      "header",
      "nav",
      "main",
      "section",
      "article",
      "aside",
      "footer",
      "form",
      "table",
    ];
    if (
      importantTags.indexOf(element.tagName.toLowerCase()) !== -1 &&
      (rect.width > 50 || rect.height > 50)
    )
      return true;
    var interactiveTags = ["button", "a", "input", "select", "textarea"];
    if (
      interactiveTags.indexOf(element.tagName.toLowerCase()) !== -1 &&
      (rect.width > 30 || rect.height > 30)
    )
      return true;
    if (depth > 8 && rect.width < 100 && rect.height < 100) return false;
    return false;
  };

  LabelRenderer.prototype.findLabelPosition = function (
    rect,
    occupiedPositions,
  ) {
    var scrollY = window.scrollY;
    var scrollX = window.scrollX;
    var positions = [
      { top: rect.top + scrollY - 24, left: rect.left + scrollX },
      { top: rect.top + scrollY - 24, left: rect.right + scrollX - 200 },
      { top: rect.top + scrollY + 4, left: rect.left + scrollX + 4 },
      { top: rect.top + scrollY + 4, left: rect.right + scrollX - 204 },
      { top: rect.bottom + scrollY + 4, left: rect.left + scrollX },
      { top: rect.bottom + scrollY + 4, left: rect.right + scrollX - 200 },
      {
        top: rect.top + scrollY + rect.height / 2 - 10,
        left: rect.left + scrollX - 210,
      },
      {
        top: rect.top + scrollY + rect.height / 2 - 10,
        left: rect.right + scrollX + 10,
      },
      { top: rect.top + scrollY - 48, left: rect.left + scrollX },
      { top: rect.bottom + scrollY + 28, left: rect.left + scrollX },
    ];
    for (var i = 0; i < positions.length; i++) {
      if (!this._isOccupied(positions[i], occupiedPositions)) {
        return {
          top: positions[i].top,
          left: positions[i].left,
          isValid: true,
        };
      }
    }
    return { top: 0, left: 0, isValid: false };
  };

  LabelRenderer.prototype._isOccupied = function (pos, occupied) {
    var w = 250,
      h = 20;
    for (var i = 0; i < occupied.length; i++) {
      var o = occupied[i];
      if (
        !(
          pos.left + w < o.left ||
          pos.left > o.right ||
          pos.top + h < o.top ||
          pos.top > o.bottom
        )
      )
        return true;
    }
    return false;
  };

  LabelRenderer.prototype.createLabel = function (element, depth) {
    var tag = element.tagName.toLowerCase();
    var id = element.id;
    var classes = element.className;
    var labelText =
      '<span class="element-inspector-label-tag">' + tag + "</span>";
    if (id)
      labelText +=
        ' <span class="element-inspector-label-id">#' + id + "</span>";
    if (classes && typeof classes === "string") {
      var classList = classes.split(/\s+/).filter(function (c) {
        return c.length > 0;
      });
      if (classList.length > 0) {
        var preview = classList.slice(0, 2).join(".");
        labelText +=
          ' <span class="element-inspector-label-class">.' +
          preview +
          "</span>";
        if (classList.length > 2)
          labelText +=
            '<span class="element-inspector-label-class">+' +
            (classList.length - 2) +
            "</span>";
      }
    }
    if (depth > 5)
      labelText +=
        ' <span style="color:#999;font-size:9px;">d' + depth + "</span>";
    var label = document.createElement("div");
    label.className = "element-inspector-label";
    label.innerHTML = labelText;
    label.title = "Right-click to copy comprehensive debug info for AI";
    return label;
  };

  LabelRenderer.prototype.addCopyToClipboard = function (label, element) {
    var self = this;
    label.addEventListener("contextmenu", function (e) {
      e.stopPropagation();
      e.preventDefault();
      var debugInfo = self._debug.gatherElementDebugInfo(element);
      navigator.clipboard
        .writeText(debugInfo)
        .then(function () {
          self._notify.showNotification("Copied!", "success");
          console.log("[ElementInspector] Copied debug info to clipboard");
          self._notify.triggerCopyCallback();
        })
        .catch(function (err) {
          console.error("[ElementInspector] Failed to copy:", err);
          self._notify.showNotification("Copy Failed", "error");
        });
    });
  };

  LabelRenderer.prototype.addHoverHighlight = function (
    label,
    box,
    element,
    onHover,
  ) {
    label.addEventListener("mouseenter", function () {
      onHover(box, element);
      box.classList.add("highlighted");
      if (element instanceof HTMLElement) {
        element.style.outline = "3px solid rgba(59,130,246,0.8)";
        element.style.outlineOffset = "2px";
      }
    });
    label.addEventListener("mouseleave", function () {
      onHover(null, null);
      box.classList.remove("highlighted");
      if (element instanceof HTMLElement) {
        element.style.outline = "";
        element.style.outlineOffset = "";
      }
    });
  };

  EI.LabelRenderer = LabelRenderer;
})();
