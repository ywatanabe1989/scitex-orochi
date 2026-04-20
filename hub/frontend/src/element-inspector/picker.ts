// @ts-nocheck
// Migrated classic-script file. Types intentionally loose during
// the big-bang JS-to-TS bundle migration. Narrow later, per-file.
/**
 * Element Inspector — layer picker (depth cycling) + element scanner.
 *
 * Loaded after overlay.js. Exports LayerPickerPanel and ElementScanner on
 * `window.__EI`. main.js wires these into the SelectionManager and the
 * top-level ElementInspector class.
 */
(function () {
  "use strict";

  var EI = (window.__EI = window.__EI || {});
  var getDepth = EI.getDepth;
  var getColorForDepth = EI.getColorForDepth;
  var LabelRenderer = EI.LabelRenderer;

  // ── LayerPickerPanel ─────────────────────────────────────────────
  function LayerPickerPanel(debugCollector, notificationManager) {
    this._panel = null;
    this._elements = [];
    this._index = 0;
    this._debug = debugCollector;
    this._notify = notificationManager;
    this._highlightCb = null;
  }

  LayerPickerPanel.prototype.setHighlightCallback = function (cb) {
    this._highlightCb = cb;
  };
  LayerPickerPanel.prototype.getCurrentDepthIndex = function () {
    return this._index;
  };
  LayerPickerPanel.prototype.getElementsAtCursor = function () {
    return this._elements;
  };
  LayerPickerPanel.prototype.getSelectedElement = function () {
    if (this._elements.length > 0 && this._index < this._elements.length)
      return this._elements[this._index];
    return null;
  };

  LayerPickerPanel.prototype.show = function (x, y, elements) {
    this.remove();
    this._elements = elements;
    this._index = 0;
    if (elements.length <= 1) return;

    var panel = document.createElement("div");
    panel.className = "element-inspector-layer-picker";
    panel.tabIndex = 0;
    panel.style.cssText =
      "position:fixed;" +
      "top:" +
      Math.min(y + 10, window.innerHeight - 300) +
      "px;" +
      "left:" +
      Math.min(x + 15, window.innerWidth - 220) +
      "px;" +
      "background:rgba(30,30,30,0.95);border:1px solid rgba(100,100,100,0.5);" +
      "border-radius:6px;padding:6px 0;min-width:200px;max-height:280px;" +
      "overflow-y:auto;z-index:10000001;" +
      "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',monospace;" +
      "font-size:11px;box-shadow:0 4px 16px rgba(0,0,0,0.4);outline:none;";

    var header = document.createElement("div");
    header.style.cssText =
      "padding:4px 10px 6px;color:#888;border-bottom:1px solid rgba(100,100,100,0.3);margin-bottom:4px;font-size:10px;";
    header.textContent = elements.length + " layers (scroll / arrow keys)";
    panel.appendChild(header);

    this._setupKeyboard(panel);
    this._renderList(panel, elements);
    document.body.appendChild(panel);
    this._panel = panel;
    this.updateSelection();
    setTimeout(function () {
      panel.focus();
    }, 10);
  };

  LayerPickerPanel.prototype._renderList = function (panel, elements) {
    var self = this;
    elements.forEach(function (el, index) {
      var item = document.createElement("div");
      item.dataset.index = String(index);
      item.style.cssText =
        "padding:5px 10px;cursor:pointer;display:flex;align-items:center;gap:6px;transition:background 0.1s;";

      var depthBar = document.createElement("span");
      var depth = getDepth(el);
      depthBar.style.cssText =
        "width:" +
        Math.min(depth * 3, 30) +
        "px;height:3px;background:" +
        getColorForDepth(depth) +
        ";border-radius:2px;flex-shrink:0;";

      var indexNum = document.createElement("span");
      indexNum.style.cssText = "color:#666;width:18px;text-align:right;";
      indexNum.textContent = String(index + 1);

      var info = document.createElement("span");
      var tag = el.tagName.toLowerCase();
      var id = el.id ? "#" + el.id : "";
      var cls =
        el.className && typeof el.className === "string"
          ? "." + el.className.split(" ")[0].substring(0, 15)
          : "";
      info.innerHTML =
        '<span style="color:#61afef">' +
        tag +
        '</span><span style="color:#e5c07b">' +
        id +
        '</span><span style="color:#98c379">' +
        cls +
        "</span>";
      info.style.cssText =
        "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";

      item.appendChild(depthBar);
      item.appendChild(indexNum);
      item.appendChild(info);

      item.addEventListener("mouseenter", function () {
        item.style.background = "rgba(100,100,100,0.3)";
      });
      item.addEventListener("mouseleave", function () {
        if (self._index !== index) item.style.background = "";
      });
      item.addEventListener("click", function () {
        self._index = index;
        if (self._highlightCb) self._highlightCb(el);
        self.updateSelection();
      });
      panel.appendChild(item);
    });
  };

  LayerPickerPanel.prototype._setupKeyboard = function (panel) {
    var self = this;
    panel.addEventListener("keydown", function (e) {
      var maxIndex = self._elements.length - 1;
      switch (e.key) {
        case "ArrowDown":
        case "Tab":
          if (!e.shiftKey) {
            e.preventDefault();
            e.stopPropagation();
            self._index = Math.min(self._index + 1, maxIndex);
          } else if (e.key === "Tab") {
            e.preventDefault();
            e.stopPropagation();
            self._index = Math.max(self._index - 1, 0);
          }
          if (self._highlightCb) self._highlightCb(self._elements[self._index]);
          self.updateSelection();
          break;
        case "ArrowUp":
          e.preventDefault();
          e.stopPropagation();
          self._index = Math.max(self._index - 1, 0);
          if (self._highlightCb) self._highlightCb(self._elements[self._index]);
          self.updateSelection();
          break;
        case "Enter":
          e.preventDefault();
          e.stopPropagation();
          self._confirmSelection();
          break;
        case "Escape":
          e.preventDefault();
          e.stopPropagation();
          self.remove();
          break;
      }
    });
  };

  LayerPickerPanel.prototype._confirmSelection = function () {
    if (this._elements.length === 0) return;
    var el = this._elements[this._index];
    if (!el) return;
    var debugInfo = this._debug.gatherElementDebugInfo(el);
    var self = this;
    navigator.clipboard
      .writeText(debugInfo)
      .then(function () {
        self._notify.showNotification("Copied!", "success");
        self._notify.triggerCopyCallback();
      })
      .catch(function (err) {
        console.error("[ElementInspector] Failed to copy:", err);
        self._notify.showNotification("Copy Failed", "error");
      });
  };

  LayerPickerPanel.prototype.updateSelection = function () {
    if (!this._panel) return;
    var self = this;
    var items = this._panel.querySelectorAll("[data-index]");
    items.forEach(function (item, index) {
      if (index === self._index) {
        item.style.background = "rgba(59,130,246,0.4)";
        item.style.borderLeft = "2px solid #3b82f6";
        item.scrollIntoView({ block: "nearest" });
      } else {
        item.style.background = "";
        item.style.borderLeft = "";
      }
    });
  };

  LayerPickerPanel.prototype.navigate = function (direction) {
    if (this._elements.length <= 1) return;
    if (direction === "down")
      this._index = Math.min(this._index + 1, this._elements.length - 1);
    else this._index = Math.max(this._index - 1, 0);
    if (this._highlightCb) this._highlightCb(this._elements[this._index]);
    this.updateSelection();
  };

  LayerPickerPanel.prototype.remove = function () {
    if (this._panel) {
      this._panel.remove();
      this._panel = null;
    }
  };

  LayerPickerPanel.prototype.reset = function () {
    this.remove();
    this._elements = [];
    this._index = 0;
  };

  EI.LayerPickerPanel = LayerPickerPanel;
})();
