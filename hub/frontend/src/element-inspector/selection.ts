// @ts-nocheck
/**
 * Element Inspector — selection manager, console collector, page structure
 * exporter, and the top-level ElementInspector class that wires everything
 * together. Loaded last; sets `window.elementInspector`.
 */
(function () {
  "use strict";

  var EI = (window.__EI = window.__EI || {});
  var getDepth = EI.getDepth;
  var NotificationManager = EI.NotificationManager;
  var DebugInfoCollector = EI.DebugInfoCollector;
  var OverlayManager = EI.OverlayManager;
  var ElementScanner = EI.ElementScanner;

  // ── SelectionManager ─────────────────────────────────────────────
  function SelectionManager(
    elementBoxMap,
    debugCollector,
    notificationManager,
  ) {
    this._selectionMode = false;
    this._start = null;
    this._rect = null;
    this._overlay = null;
    this._selectedElements = new Set();
    this._boxMap = elementBoxMap;
    this._debug = debugCollector;
    this._notify = notificationManager;
    this._scanner = null;

    var self = this;
    this._onMouseDown = function (e) {
      self._handleMouseDown(e);
    };
    this._onMouseMove = function (e) {
      self._handleMouseMove(e);
    };
    this._onMouseUp = function (e) {
      self._handleMouseUp(e);
    };
  }

  SelectionManager.prototype.setElementScanner = function (scanner) {
    this._scanner = scanner;
  };
  SelectionManager.prototype.isActive = function () {
    return this._selectionMode;
  };

  SelectionManager.prototype.startSelectionMode = function () {
    this._selectionMode = true;
    document.body.classList.add("element-inspector-selection-mode");
    this._overlay = document.createElement("div");
    this._overlay.className = "selection-overlay";
    document.body.appendChild(this._overlay);
    this._notify.showNotification("Drag to select area", "success");
    document.addEventListener("mousedown", this._onMouseDown);
    document.addEventListener("mousemove", this._onMouseMove);
    document.addEventListener("mouseup", this._onMouseUp);
  };

  SelectionManager.prototype.cancelSelectionMode = function () {
    this._selectionMode = false;
    document.body.classList.remove("element-inspector-selection-mode");
    this._clearHighlights();
    if (this._overlay) {
      this._overlay.remove();
      this._overlay = null;
    }
    if (this._rect) {
      this._rect.remove();
      this._rect = null;
    }
    document.removeEventListener("mousedown", this._onMouseDown);
    document.removeEventListener("mousemove", this._onMouseMove);
    document.removeEventListener("mouseup", this._onMouseUp);
    this._start = null;
  };

  SelectionManager.prototype._handleMouseDown = function (e) {
    if (!this._selectionMode) return;
    e.preventDefault();
    this._start = { x: e.clientX, y: e.clientY };
    this._rect = document.createElement("div");
    this._rect.className = "selection-rectangle";
    this._rect.style.left = e.clientX + "px";
    this._rect.style.top = e.clientY + "px";
    this._rect.style.width = "0px";
    this._rect.style.height = "0px";
    document.body.appendChild(this._rect);
  };

  SelectionManager.prototype._handleMouseMove = function (e) {
    if (!this._selectionMode || !this._start || !this._rect) return;
    e.preventDefault();
    var left = Math.min(this._start.x, e.clientX);
    var top = Math.min(this._start.y, e.clientY);
    var width = Math.abs(e.clientX - this._start.x);
    var height = Math.abs(e.clientY - this._start.y);
    this._rect.style.left = left + "px";
    this._rect.style.top = top + "px";
    this._rect.style.width = width + "px";
    this._rect.style.height = height + "px";
  };

  SelectionManager.prototype._handleMouseUp = function (e) {
    if (!this._selectionMode || !this._start || !this._rect) return;
    e.preventDefault();
    var left = Math.min(this._start.x, e.clientX);
    var top = Math.min(this._start.y, e.clientY);
    var width = Math.abs(e.clientX - this._start.x);
    var height = Math.abs(e.clientY - this._start.y);
    if (width < 5 || height < 5) {
      this.cancelSelectionMode();
      this._notify.showNotification("Selection too small", "error");
      return;
    }
    var rect = { left: left, top: top, width: width, height: height };
    var selectedElements = this._findElementsInRect(rect);
    console.log(
      "[ElementInspector] Found " +
        selectedElements.length +
        " elements in selection",
    );
    var info = this._gatherSelectionInfo(selectedElements, rect);
    var self = this;
    navigator.clipboard
      .writeText(info)
      .then(function () {
        self._notify.showNotification(
          selectedElements.length + " elements copied!",
          "success",
        );
        self._notify.triggerCopyCallback();
      })
      .catch(function (err) {
        console.error("[ElementInspector] Failed to copy:", err);
        self._notify.showNotification("Copy Failed", "error");
      });
    this.cancelSelectionMode();
  };

  SelectionManager.prototype._clearHighlights = function () {
    var self = this;
    this._boxMap.forEach(function (element, box) {
      if (self._selectedElements.has(element)) {
        box.style.borderWidth = "2px";
        box.style.background = "rgba(255,255,255,0.01)";
        box.style.transform = "";
        box.style.zIndex = "";
      }
    });
    this._selectedElements.forEach(function (element) {
      if (element instanceof HTMLElement)
        element.classList.remove("element-inspector-selected");
    });
    this._selectedElements.clear();
  };

  SelectionManager.prototype._findElementsInRect = function (rect) {
    var selected = [];
    var all = document.querySelectorAll("*");
    var selRect = {
      left: rect.left,
      top: rect.top,
      right: rect.left + rect.width,
      bottom: rect.top + rect.height,
    };

    var targetDepth = null;
    if (this._scanner) {
      var depthEl = this._scanner.getDepthSelectedElement();
      if (depthEl) targetDepth = getDepth(depthEl);
    }

    for (var i = 0; i < all.length; i++) {
      var element = all[i];
      if (
        element.closest("#element-inspector-overlay") ||
        element.classList.contains("selection-rectangle") ||
        element.classList.contains("selection-overlay") ||
        element.closest(".element-inspector-layer-picker")
      )
        continue;
      var tagName = element.tagName.toLowerCase();
      if (
        [
          "script",
          "style",
          "link",
          "meta",
          "head",
          "noscript",
          "br",
          "html",
          "body",
        ].indexOf(tagName) !== -1
      )
        continue;
      if (element instanceof HTMLElement) {
        var computed = window.getComputedStyle(element);
        if (computed.display === "none" || computed.visibility === "hidden")
          continue;
      }
      if (targetDepth !== null && Math.abs(getDepth(element) - targetDepth) > 2)
        continue;
      var elRect = element.getBoundingClientRect();
      if (elRect.width < 10 || elRect.height < 10) continue;
      var intersects = !(
        elRect.right < selRect.left ||
        elRect.left > selRect.right ||
        elRect.bottom < selRect.top ||
        elRect.top > selRect.bottom
      );
      if (intersects) selected.push(element);
    }
    return selected;
  };

  SelectionManager.prototype._gatherSelectionInfo = function (elements, rect) {
    var info =
      "# Rectangle Selection Debug Information\n\n" +
      "## Selection Area\n- Position: (" +
      Math.round(rect.left) +
      ", " +
      Math.round(rect.top) +
      ")\n" +
      "- Size: " +
      Math.round(rect.width) +
      "x" +
      Math.round(rect.height) +
      "px\n" +
      "- URL: " +
      window.location.href +
      "\n- Timestamp: " +
      new Date().toISOString() +
      "\n- Elements Found: " +
      elements.length +
      "\n\n---\n\n";

    var types = {};
    elements.forEach(function (el) {
      var tag = el.tagName.toLowerCase();
      types[tag] = (types[tag] || 0) + 1;
    });
    info += "## Element Type Summary\n";
    Object.entries(types)
      .sort(function (a, b) {
        return b[1] - a[1];
      })
      .forEach(function (kv) {
        info += "- " + kv[0] + ": " + kv[1] + "\n";
      });
    info += "\n---\n\n";

    var maxDetailed = 20;
    var detailedCount = Math.min(elements.length, maxDetailed);
    info +=
      "## Detailed Element Information (" +
      detailedCount +
      " of " +
      elements.length +
      " elements)\n\n---\n\n";
    var self = this;
    elements.slice(0, maxDetailed).forEach(function (element, index) {
      info += "# Element " + (index + 1) + "/" + elements.length + "\n\n";
      info += self._debug.gatherElementDebugInfo(element);
      info += "\n" + "=".repeat(80) + "\n\n";
    });

    if (elements.length > maxDetailed) {
      info +=
        "## Remaining Elements (" +
        (elements.length - maxDetailed) +
        " elements - basic info)\n\n";
      elements.slice(maxDetailed).forEach(function (element, index) {
        var actualIndex = maxDetailed + index + 1;
        var selector = self._debug.buildCSSSelector(element);
        var r = element.getBoundingClientRect();
        var text = (element.textContent || "").trim().substring(0, 50);
        info += "### " + actualIndex + ". " + selector + "\n";
        info +=
          "- Position: (" +
          Math.round(r.left) +
          ", " +
          Math.round(r.top) +
          ") | Size: " +
          Math.round(r.width) +
          "x" +
          Math.round(r.height) +
          "px\n";
        if (text)
          info += '- Text: "' + text + (text.length > 50 ? "..." : "") + '"\n';
        info += "\n";
      });
    }
    info +=
      "\n---\nGenerated by Element Inspector - Rectangle Selection Mode\n";
    return info;
  };

  EI.SelectionManager = SelectionManager;
})();
