// @ts-nocheck
/**
 * Element Inspector — element scanner (overlay box rendering, batch
 * loading, hover/click/wheel handling).
 *
 * Loaded after picker.js. Exports ElementScanner on `window.__EI`.
 */
(function () {
  "use strict";

  var EI = (window.__EI = window.__EI || {});
  var getDepth = EI.getDepth;
  var getColorForDepth = EI.getColorForDepth;
  var LabelRenderer = EI.LabelRenderer;
  var LayerPickerPanel = EI.LayerPickerPanel;

  var BATCH_SIZE = 512;
  var MIN_SIZE = 10;

  function ElementScanner(debugCollector, notificationManager) {
    this._debug = debugCollector;
    this._notify = notificationManager;
    this._elementBoxMap = new Map();
    this._hoveredBox = null;
    this._hoveredElement = null;
    this._batchStart = 0;
    this._allVisible = [];
    this._overlayRef = null;
    this._lastCursorX = 0;
    this._lastCursorY = 0;
    this._wheelHandler = null;
    this._directHighlight = null;

    this._layerPicker = new LayerPickerPanel(
      debugCollector,
      notificationManager,
    );
    this._labelRenderer = new LabelRenderer(
      debugCollector,
      notificationManager,
    );

    var self = this;
    this._layerPicker.setHighlightCallback(function (el) {
      if (self._overlayRef) self._highlightElement(el, self._overlayRef);
    });
  }

  ElementScanner.prototype.getElementBoxMap = function () {
    return this._elementBoxMap;
  };
  ElementScanner.prototype.getDepthSelectedElement = function () {
    return this._layerPicker.getSelectedElement() || this._hoveredElement;
  };

  ElementScanner.prototype.clearElementBoxMap = function () {
    this._elementBoxMap.clear();
    this._hoveredBox = null;
    this._hoveredElement = null;
    this._batchStart = 0;
    this._allVisible = [];
    this._overlayRef = null;
    if (this._wheelHandler) {
      document.removeEventListener("wheel", this._wheelHandler);
      this._wheelHandler = null;
    }
    this._layerPicker.reset();
    this._clearDirectHighlight();
  };

  ElementScanner.prototype.scanElements = function (overlayContainer) {
    this._overlayRef = overlayContainer;
    if (this._allVisible.length === 0) this._collectVisible();
    this._renderBatch(overlayContainer);
    this._setupWheel(overlayContainer);
  };

  ElementScanner.prototype._collectVisible = function () {
    var startTime = performance.now();
    var all = document.querySelectorAll("*");
    for (var i = 0; i < all.length; i++) {
      var element = all[i];
      if (!element || !element.tagName) continue;
      if (element.closest("#element-inspector-overlay")) continue;
      var tagName = element.tagName.toLowerCase();
      if (
        ["script", "style", "link", "meta", "head", "noscript", "br"].indexOf(
          tagName,
        ) !== -1
      )
        continue;
      var rect = element.getBoundingClientRect();
      if (rect.width < MIN_SIZE || rect.height < MIN_SIZE) continue;
      if (element instanceof HTMLElement) {
        if (
          element.offsetParent === null &&
          tagName !== "body" &&
          tagName !== "html"
        ) {
          if (element.style.display === "none") continue;
        }
      }
      this._allVisible.push(element);
    }
    var elapsed = (performance.now() - startTime).toFixed(1);
    console.log(
      "[ElementInspector] Found " +
        this._allVisible.length +
        " visible elements in " +
        elapsed +
        "ms",
    );
  };

  ElementScanner.prototype._renderBatch = function (overlayContainer) {
    var startTime = performance.now();
    var fragment = document.createDocumentFragment();
    var occupiedPositions = [];
    var scrollY = window.scrollY;
    var scrollX = window.scrollX;
    var batchEnd = Math.min(
      this._batchStart + BATCH_SIZE,
      this._allVisible.length,
    );
    var count = 0;
    var self = this;

    for (var i = this._batchStart; i < batchEnd; i++) {
      var element = this._allVisible[i];
      var rect = element.getBoundingClientRect();
      var margin = 100;
      if (
        rect.bottom < -margin ||
        rect.top > window.innerHeight + margin ||
        rect.right < -margin ||
        rect.left > window.innerWidth + margin
      )
        continue;

      var depth = getDepth(element);
      var color = getColorForDepth(depth);
      var area = rect.width * rect.height;
      var borderWidth = area > 100000 ? 1 : area > 10000 ? 1.5 : 2;

      var box = document.createElement("div");
      box.className = "element-inspector-box";
      box.style.cssText =
        "top:" +
        (rect.top + scrollY) +
        "px;left:" +
        (rect.left + scrollX) +
        "px;" +
        "width:" +
        rect.width +
        "px;height:" +
        rect.height +
        "px;" +
        "border-color:" +
        color +
        ";border-width:" +
        borderWidth +
        "px;";

      var id = element.id ? "#" + element.id : "";
      box.title =
        "Right-click to copy | Scroll to cycle depth: " +
        element.tagName.toLowerCase() +
        id;

      this._elementBoxMap.set(box, element);

      (function (b, el) {
        b.addEventListener("mouseenter", function () {
          self._hoveredBox = b;
          self._hoveredElement = el;
        });
        b.addEventListener("mouseleave", function () {
          if (self._hoveredBox === b) {
            self._hoveredBox = null;
            self._hoveredElement = null;
          }
        });

        b.addEventListener("click", function (e) {
          b.style.pointerEvents = "none";
          var under = document.elementFromPoint(e.clientX, e.clientY);
          b.style.pointerEvents = "";
          if (under && under !== b) {
            var clickEvt = new MouseEvent("click", {
              bubbles: true,
              cancelable: true,
              view: window,
              clientX: e.clientX,
              clientY: e.clientY,
            });
            under.dispatchEvent(clickEvt);
          }
        });

        b.addEventListener("contextmenu", function (e) {
          e.preventDefault();
          e.stopPropagation();
          var selEl = self._hoveredElement || el;
          var selBox = self._hoveredBox || b;
          selBox.classList.add("highlighted");
          var debugInfo = self._debug.gatherElementDebugInfo(selEl);
          navigator.clipboard
            .writeText(debugInfo)
            .then(function () {
              self._notify.showNotification("Copied!", "success");
              console.log("[ElementInspector] Copied:", debugInfo);
              self._notify.triggerCopyCallback();
            })
            .catch(function (err) {
              console.error("[ElementInspector] Copy failed:", err);
              self._notify.showNotification("Copy Failed", "error");
              selBox.classList.remove("highlighted");
            });
        });
      })(box, element);

      if (this._labelRenderer.shouldShowLabel(element, rect, depth)) {
        var label = this._labelRenderer.createLabel(element, depth);
        if (label) {
          var labelPos = this._labelRenderer.findLabelPosition(
            rect,
            occupiedPositions,
          );
          if (labelPos.isValid) {
            label.style.top = labelPos.top + "px";
            label.style.left = labelPos.left + "px";
            this._labelRenderer.addCopyToClipboard(label, element);
            this._labelRenderer.addHoverHighlight(
              label,
              box,
              element,
              function (b, e) {
                self._hoveredBox = b;
                self._hoveredElement = e;
              },
            );
            occupiedPositions.push({
              top: labelPos.top - 8,
              left: labelPos.left - 8,
              bottom: labelPos.top + 20 + 8,
              right: labelPos.left + 250 + 8,
            });
            fragment.appendChild(label);
          }
        }
      }
      fragment.appendChild(box);
      count++;
    }

    overlayContainer.appendChild(fragment);
    var elapsed = (performance.now() - startTime).toFixed(1);
    var total = this._allVisible.length;
    var remaining = total - batchEnd;
    console.log(
      "[ElementInspector] Rendered " +
        count +
        " elements (" +
        (this._batchStart + 1) +
        "-" +
        batchEnd +
        "/" +
        total +
        ") in " +
        elapsed +
        "ms" +
        (remaining > 0
          ? " | Ctrl+I for next " + Math.min(remaining, BATCH_SIZE)
          : ""),
    );
    if (remaining > 0)
      this._notify.showNotification(
        batchEnd + "/" + total + " elements | Ctrl+I for more",
        "success",
        2000,
      );
  };

  ElementScanner.prototype.loadNextBatch = function () {
    if (!this._overlayRef) return false;
    var total = this._allVisible.length;
    var nextStart = this._batchStart + BATCH_SIZE;
    if (nextStart >= total) {
      this._notify.showNotification("All elements loaded", "success");
      return false;
    }
    this._batchStart = nextStart;
    this._renderBatch(this._overlayRef);
    return true;
  };

  ElementScanner.prototype._setupWheel = function (overlayContainer) {
    var self = this;
    this._wheelHandler = function (e) {
      if (!overlayContainer.contains(e.target)) return;
      var cursorMoved =
        Math.abs(e.clientX - self._lastCursorX) > 5 ||
        Math.abs(e.clientY - self._lastCursorY) > 5;
      if (cursorMoved) {
        self._lastCursorX = e.clientX;
        self._lastCursorY = e.clientY;
        var elements = self._getElementsAtPoint(e.clientX, e.clientY);
        self._layerPicker.show(e.clientX, e.clientY, elements);
      }
      var elements = self._layerPicker.getElementsAtCursor();
      if (elements.length <= 1) {
        self._layerPicker.remove();
        return;
      }
      e.preventDefault();
      e.stopPropagation();
      self._layerPicker.navigate(e.deltaY > 0 ? "down" : "up");
    };
    document.addEventListener("wheel", this._wheelHandler, { passive: false });
  };

  ElementScanner.prototype._getElementsAtPoint = function (x, y) {
    var elements = [];
    var allAtPoint = document.elementsFromPoint(x, y);
    for (var i = 0; i < allAtPoint.length; i++) {
      var el = allAtPoint[i];
      if (!el || !el.tagName) continue;
      if (el.closest("#element-inspector-overlay")) continue;
      if (el.closest(".element-inspector-layer-picker")) continue;
      var tag = el.tagName.toLowerCase();
      if (["html", "body", "script", "style", "head"].indexOf(tag) !== -1)
        continue;
      elements.push(el);
    }
    return elements;
  };

  ElementScanner.prototype._clearDirectHighlight = function () {
    if (this._directHighlight instanceof HTMLElement) {
      this._directHighlight.style.outline = "";
      this._directHighlight.style.outlineOffset = "";
    }
    this._directHighlight = null;
  };

  ElementScanner.prototype._highlightElement = function (
    element,
    overlayContainer,
  ) {
    overlayContainer
      .querySelectorAll(".element-inspector-box.highlighted")
      .forEach(function (box) {
        box.classList.remove("highlighted");
      });
    this._clearDirectHighlight();
    var found = false;
    for (var entry of this._elementBoxMap) {
      if (entry[1] === element) {
        entry[0].classList.add("highlighted");
        this._hoveredBox = entry[0];
        this._hoveredElement = element;
        found = true;
        break;
      }
    }
    if (!found && element instanceof HTMLElement) {
      element.style.outline = "3px solid #3b82f6";
      element.style.outlineOffset = "2px";
      this._directHighlight = element;
      this._hoveredElement = element;
    }
  };

  EI.ElementScanner = ElementScanner;
})();

// Auto-generated module re-exports for symbols assigned to `window`
// inside the file-level IIFE above. These run after the IIFE's side
// effects so other ES modules can import these names instead of
// reaching into `window`.
export const _hoveredBox = (window as any)._hoveredBox;
export const _hoveredElement = (window as any)._hoveredElement;
export const _lastCursorX = (window as any)._lastCursorX;
export const _lastCursorY = (window as any)._lastCursorY;
