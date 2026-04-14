/**
 * Element Inspector - Visual Debugging Tool
 * Ported from scitex-cloud (TypeScript) to vanilla JS for orochi.
 *
 * Shows all HTML elements with colored rectangles and labels.
 * Toggle with Alt+I (I for Inspector)
 *
 * Shortcuts:
 *   Alt+I           Toggle inspector overlay
 *   Ctrl+I          Load next 512 elements (when active)
 *   Ctrl+Alt+I      Rectangle selection mode
 *   Ctrl+Shift+I    Debug snapshot (console logs to clipboard)
 *   Scroll wheel    Cycle through overlapped elements
 *   Right-click     Copy element debug info
 *   Left-click      Pass through to underlying element
 *   Escape          Deactivate / Cancel selection
 */
(function () {
  "use strict";

  // ── Depth utilities ──────────────────────────────────────────────
  var DEPTH_COLORS = [
    "#3B82F6", // Blue (depth 0-2)
    "#10B981", // Green (depth 3-5)
    "#F59E0B", // Yellow (depth 6-8)
    "#EF4444", // Red (depth 9-11)
    "#EC4899", // Pink (depth 12+)
  ];

  function getDepth(element) {
    var depth = 0;
    var current = element;
    while (current && current !== document.body) {
      depth++;
      current = current.parentElement;
    }
    return depth;
  }

  function getColorForDepth(depth) {
    var index = Math.min(Math.floor(depth / 3), DEPTH_COLORS.length - 1);
    return DEPTH_COLORS[index];
  }

  function hexToRgba(hex, alpha) {
    var result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    if (!result) return "rgba(59, 130, 246, " + alpha + ")";
    var r = parseInt(result[1], 16);
    var g = parseInt(result[2], 16);
    var b = parseInt(result[3], 16);
    return "rgba(" + r + ", " + g + ", " + b + ", " + alpha + ")";
  }

  // ── NotificationManager ──────────────────────────────────────────
  function NotificationManager() {
    this._onCopyCallback = null;
  }

  NotificationManager.prototype.setOnCopyCallback = function (cb) {
    this._onCopyCallback = cb;
  };

  NotificationManager.prototype.triggerCopyCallback = function () {
    var self = this;
    if (self._onCopyCallback) {
      setTimeout(function () {
        if (self._onCopyCallback) self._onCopyCallback();
      }, 400);
    }
  };

  NotificationManager.prototype.showNotification = function (message, type, duration) {
    duration = duration || 1000;
    var el = document.createElement("div");
    el.textContent = message;
    el.style.cssText =
      "position:fixed;top:16px;right:16px;padding:10px 20px;" +
      "background:" + (type === "success" ? "rgba(16,185,129,0.95)" : "rgba(239,68,68,0.95)") + ";" +
      "color:#fff;border-radius:6px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;" +
      "font-size:13px;font-weight:600;z-index:10000000;" +
      "box-shadow:0 4px 12px rgba(0,0,0,0.25);" +
      "opacity:0;transform:translateY(-10px) scale(0.95);" +
      "transition:opacity 0.2s ease,transform 0.2s ease;";
    document.body.appendChild(el);
    requestAnimationFrame(function () {
      el.style.opacity = "1";
      el.style.transform = "translateY(0) scale(1)";
    });
    setTimeout(function () {
      el.style.opacity = "0";
      el.style.transform = "translateY(-10px) scale(0.95)";
      setTimeout(function () { el.remove(); }, 200);
    }, duration);
  };

  NotificationManager.prototype.showCameraFlash = function () {
    var flash = document.createElement("div");
    flash.style.cssText =
      "position:fixed;top:0;left:0;right:0;bottom:0;" +
      "background:rgba(255,255,255,0.4);z-index:9999999;" +
      "pointer-events:none;opacity:1;transition:opacity 0.1s ease;";
    document.body.appendChild(flash);
    setTimeout(function () { flash.style.opacity = "0"; }, 30);
    setTimeout(function () { flash.remove(); }, 130);
  };

  // ── DebugInfoCollector ───────────────────────────────────────────
  function DebugInfoCollector() {}

  DebugInfoCollector.prototype.buildCSSSelector = function (element) {
    var tag = element.tagName.toLowerCase();
    var id = element.id;
    var classes = element.className;
    var selector = tag;
    if (id) selector += "#" + id;
    if (classes && typeof classes === "string") {
      var classList = classes.split(/\s+/).filter(function (c) { return c; });
      if (classList.length > 0) selector += "." + classList.join(".");
    }
    return selector;
  };

  DebugInfoCollector.prototype.getXPath = function (element) {
    if (element.id) return '//*[@id="' + element.id + '"]';
    var parts = [];
    var current = element;
    while (current && current.nodeType === Node.ELEMENT_NODE) {
      var index = 0;
      var sibling = current.previousSibling;
      while (sibling) {
        if (sibling.nodeType === Node.ELEMENT_NODE && sibling.nodeName === current.nodeName) index++;
        sibling = sibling.previousSibling;
      }
      var tagName = current.nodeName.toLowerCase();
      var pathIndex = index > 0 ? "[" + (index + 1) + "]" : "";
      parts.unshift(tagName + pathIndex);
      current = current.parentElement;
    }
    return "/" + parts.join("/");
  };

  DebugInfoCollector.prototype._getEventListeners = function (element) {
    var listeners = [];
    var eventAttrs = ["onclick", "onload", "onchange", "onsubmit", "onmouseover", "onmouseout"];
    eventAttrs.forEach(function (attr) {
      if (element.hasAttribute(attr)) listeners.push(attr);
    });
    return listeners;
  };

  DebugInfoCollector.prototype._getParentChain = function (element) {
    var chain = [];
    var current = element.parentElement;
    var depth = 0;
    var self = this;
    while (current && depth < 5) {
      chain.push(self.buildCSSSelector(current));
      current = current.parentElement;
      depth++;
    }
    return chain;
  };

  DebugInfoCollector.prototype._getAppliedStylesheets = function () {
    var sheets = [];
    for (var i = 0; i < document.styleSheets.length; i++) {
      try {
        var sheet = document.styleSheets[i];
        if (sheet.href) sheets.push(sheet.href);
        else if (sheet.ownerNode) sheets.push("<inline style>");
      } catch (e) {
        sheets.push("<cross-origin stylesheet>");
      }
    }
    return sheets;
  };

  DebugInfoCollector.prototype._getMatchingCSSRules = function (element) {
    var matchingRules = [];
    for (var i = 0; i < document.styleSheets.length; i++) {
      try {
        var sheet = document.styleSheets[i];
        if (!sheet.cssRules) continue;
        for (var j = 0; j < sheet.cssRules.length; j++) {
          var rule = sheet.cssRules[j];
          if (rule instanceof CSSStyleRule) {
            try {
              if (element.matches(rule.selectorText)) {
                matchingRules.push({
                  selector: rule.selectorText,
                  cssText: rule.cssText.substring(0, 200) + (rule.cssText.length > 200 ? "..." : ""),
                  source: sheet.href || "<inline style>",
                  ruleIndex: j,
                });
              }
            } catch (e) { /* invalid selector */ }
          }
        }
      } catch (e) { /* CORS */ }
    }
    return matchingRules;
  };

  DebugInfoCollector.prototype.gatherElementDebugInfo = function (element) {
    var info = {};
    info.url = window.location.href;
    info.timestamp = new Date().toISOString();

    var className = typeof element.className === "string" ? element.className : "";
    info.element = {
      tag: element.tagName.toLowerCase(),
      id: element.id || null,
      classes: className ? className.split(/\s+/).filter(function (c) { return c; }) : [],
      selector: this.buildCSSSelector(element),
      xpath: this.getXPath(element),
    };

    info.attributes = {};
    for (var i = 0; i < element.attributes.length; i++) {
      var attr = element.attributes[i];
      info.attributes[attr.name] = attr.value;
    }

    if (element instanceof HTMLElement) {
      var computed = window.getComputedStyle(element);
      info.styles = {
        display: computed.display, position: computed.position,
        width: computed.width, height: computed.height,
        margin: computed.margin, padding: computed.padding,
        backgroundColor: computed.backgroundColor, color: computed.color,
        fontSize: computed.fontSize, fontFamily: computed.fontFamily,
        zIndex: computed.zIndex, opacity: computed.opacity,
        visibility: computed.visibility, overflow: computed.overflow,
      };
      if (element.style.cssText) info.inlineStyles = element.style.cssText;
      var rect = element.getBoundingClientRect();
      info.dimensions = { width: rect.width, height: rect.height, top: rect.top, left: rect.left, bottom: rect.bottom, right: rect.right };
      info.scroll = { scrollTop: element.scrollTop, scrollLeft: element.scrollLeft, scrollHeight: element.scrollHeight, scrollWidth: element.scrollWidth };
      info.content = {
        innerHTML: element.innerHTML.substring(0, 200) + (element.innerHTML.length > 200 ? "..." : ""),
        textContent: (element.textContent || "").substring(0, 200) + ((element.textContent || "").length > 200 ? "..." : ""),
      };
    }

    info.eventListeners = this._getEventListeners(element);
    info.parentChain = this._getParentChain(element);
    info.appliedStylesheets = this._getAppliedStylesheets();
    info.matchingCSSRules = this._getMatchingCSSRules(element);

    return this._formatDebugInfoForAI(info);
  };

  DebugInfoCollector.prototype._formatDebugInfoForAI = function (info) {
    var attrs = Object.entries(info.attributes || {}).map(function (kv) { return "- " + kv[0] + ": " + kv[1]; }).join("\n");
    var styles = Object.entries(info.styles || {}).map(function (kv) { return "- " + kv[0] + ": " + kv[1]; }).join("\n");
    var listeners = (info.eventListeners && info.eventListeners.length > 0) ? info.eventListeners.join(", ") : "none detected";
    var parents = (info.parentChain || []).map(function (p, i) { return (i + 1) + ". " + p; }).join("\n");
    var sheets = (info.appliedStylesheets || []).slice(0, 10).map(function (s, i) { return (i + 1) + ". " + s; }).join("\n");
    var rulesCount = (info.matchingCSSRules || []).length;
    var rulesText = rulesCount > 0
      ? info.matchingCSSRules.slice(0, 10).map(function (rule, i) {
          return "\n### " + (i + 1) + ". " + rule.selector + "\n- Source: " + rule.source + "\n- Rule Index: " + rule.ruleIndex + "\n- CSS: " + rule.cssText + "\n";
        }).join("\n")
      : "No matching rules found (may be due to CORS restrictions)";

    return "# Element Debug Information\n\n" +
      "## Page Context\n- URL: " + info.url + "\n- Timestamp: " + info.timestamp + "\n\n" +
      "## Element Identification\n- Tag: <" + info.element.tag + ">\n- ID: " + (info.element.id || "none") +
      "\n- Classes: " + (info.element.classes.join(", ") || "none") +
      "\n- CSS Selector: " + info.element.selector +
      "\n- XPath: " + info.element.xpath + "\n\n" +
      "## Attributes\n" + (attrs || "none") + "\n\n" +
      "## Computed Styles\n" + (styles || "none") + "\n\n" +
      (info.inlineStyles ? "## Inline Styles\n" + info.inlineStyles + "\n\n" : "") +
      "## Dimensions & Position\n- Width: " + (info.dimensions ? info.dimensions.width : "?") + "px\n" +
      "- Height: " + (info.dimensions ? info.dimensions.height : "?") + "px\n" +
      "- Top: " + (info.dimensions ? info.dimensions.top : "?") + "px\n" +
      "- Left: " + (info.dimensions ? info.dimensions.left : "?") + "px\n\n" +
      "## Scroll State\n- scrollTop: " + (info.scroll ? info.scroll.scrollTop : "?") +
      "\n- scrollLeft: " + (info.scroll ? info.scroll.scrollLeft : "?") + "\n\n" +
      "## Content (truncated)\n" + (info.content ? info.content.textContent : "none") + "\n\n" +
      "## Event Listeners\n" + listeners + "\n\n" +
      "## Parent Chain\n" + parents + "\n\n" +
      "## Applied Stylesheets\n" + sheets + "\n\n" +
      "## Matching CSS Rules (" + rulesCount + " rules)\n" + rulesText + "\n\n" +
      "---\nThis debug information was captured by Element Inspector.\n";
  };

  // ── OverlayManager ───────────────────────────────────────────────
  function OverlayManager() {
    this._container = null;
  }

  OverlayManager.prototype.isActive = function () { return this._container !== null; };
  OverlayManager.prototype.getContainer = function () { return this._container; };

  OverlayManager.prototype.createOverlay = function () {
    this._container = document.createElement("div");
    this._container.id = "element-inspector-overlay";
    var docHeight = Math.max(
      document.body.scrollHeight, document.documentElement.scrollHeight,
      document.body.offsetHeight, document.documentElement.offsetHeight,
      document.body.clientHeight, document.documentElement.clientHeight
    );
    this._container.style.cssText =
      "position:absolute;top:0;left:0;width:100%;height:" + docHeight + "px;" +
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

  // ── LabelRenderer ────────────────────────────────────────────────
  function LabelRenderer(debugCollector, notificationManager) {
    this._debug = debugCollector;
    this._notify = notificationManager;
  }

  LabelRenderer.prototype.shouldShowLabel = function (element, rect, depth) {
    if (element.id) return rect.width > 20 && rect.height > 20;
    if (rect.width > 100 || rect.height > 100) return true;
    var importantTags = ["header", "nav", "main", "section", "article", "aside", "footer", "form", "table"];
    if (importantTags.indexOf(element.tagName.toLowerCase()) !== -1 && (rect.width > 50 || rect.height > 50)) return true;
    var interactiveTags = ["button", "a", "input", "select", "textarea"];
    if (interactiveTags.indexOf(element.tagName.toLowerCase()) !== -1 && (rect.width > 30 || rect.height > 30)) return true;
    if (depth > 8 && rect.width < 100 && rect.height < 100) return false;
    return false;
  };

  LabelRenderer.prototype.findLabelPosition = function (rect, occupiedPositions) {
    var scrollY = window.scrollY;
    var scrollX = window.scrollX;
    var positions = [
      { top: rect.top + scrollY - 24, left: rect.left + scrollX },
      { top: rect.top + scrollY - 24, left: rect.right + scrollX - 200 },
      { top: rect.top + scrollY + 4, left: rect.left + scrollX + 4 },
      { top: rect.top + scrollY + 4, left: rect.right + scrollX - 204 },
      { top: rect.bottom + scrollY + 4, left: rect.left + scrollX },
      { top: rect.bottom + scrollY + 4, left: rect.right + scrollX - 200 },
      { top: rect.top + scrollY + rect.height / 2 - 10, left: rect.left + scrollX - 210 },
      { top: rect.top + scrollY + rect.height / 2 - 10, left: rect.right + scrollX + 10 },
      { top: rect.top + scrollY - 48, left: rect.left + scrollX },
      { top: rect.bottom + scrollY + 28, left: rect.left + scrollX },
    ];
    for (var i = 0; i < positions.length; i++) {
      if (!this._isOccupied(positions[i], occupiedPositions)) {
        return { top: positions[i].top, left: positions[i].left, isValid: true };
      }
    }
    return { top: 0, left: 0, isValid: false };
  };

  LabelRenderer.prototype._isOccupied = function (pos, occupied) {
    var w = 250, h = 20;
    for (var i = 0; i < occupied.length; i++) {
      var o = occupied[i];
      if (!(pos.left + w < o.left || pos.left > o.right || pos.top + h < o.top || pos.top > o.bottom)) return true;
    }
    return false;
  };

  LabelRenderer.prototype.createLabel = function (element, depth) {
    var tag = element.tagName.toLowerCase();
    var id = element.id;
    var classes = element.className;
    var labelText = '<span class="element-inspector-label-tag">' + tag + "</span>";
    if (id) labelText += ' <span class="element-inspector-label-id">#' + id + "</span>";
    if (classes && typeof classes === "string") {
      var classList = classes.split(/\s+/).filter(function (c) { return c.length > 0; });
      if (classList.length > 0) {
        var preview = classList.slice(0, 2).join(".");
        labelText += ' <span class="element-inspector-label-class">.' + preview + "</span>";
        if (classList.length > 2) labelText += '<span class="element-inspector-label-class">+' + (classList.length - 2) + "</span>";
      }
    }
    if (depth > 5) labelText += ' <span style="color:#999;font-size:9px;">d' + depth + "</span>";
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
      navigator.clipboard.writeText(debugInfo).then(function () {
        self._notify.showNotification("Copied!", "success");
        console.log("[ElementInspector] Copied debug info to clipboard");
        self._notify.triggerCopyCallback();
      }).catch(function (err) {
        console.error("[ElementInspector] Failed to copy:", err);
        self._notify.showNotification("Copy Failed", "error");
      });
    });
  };

  LabelRenderer.prototype.addHoverHighlight = function (label, box, element, onHover) {
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

  // ── LayerPickerPanel ─────────────────────────────────────────────
  function LayerPickerPanel(debugCollector, notificationManager) {
    this._panel = null;
    this._elements = [];
    this._index = 0;
    this._debug = debugCollector;
    this._notify = notificationManager;
    this._highlightCb = null;
  }

  LayerPickerPanel.prototype.setHighlightCallback = function (cb) { this._highlightCb = cb; };
  LayerPickerPanel.prototype.getCurrentDepthIndex = function () { return this._index; };
  LayerPickerPanel.prototype.getElementsAtCursor = function () { return this._elements; };
  LayerPickerPanel.prototype.getSelectedElement = function () {
    if (this._elements.length > 0 && this._index < this._elements.length) return this._elements[this._index];
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
      "top:" + Math.min(y + 10, window.innerHeight - 300) + "px;" +
      "left:" + Math.min(x + 15, window.innerWidth - 220) + "px;" +
      "background:rgba(30,30,30,0.95);border:1px solid rgba(100,100,100,0.5);" +
      "border-radius:6px;padding:6px 0;min-width:200px;max-height:280px;" +
      "overflow-y:auto;z-index:10000001;" +
      "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',monospace;" +
      "font-size:11px;box-shadow:0 4px 16px rgba(0,0,0,0.4);outline:none;";

    var header = document.createElement("div");
    header.style.cssText = "padding:4px 10px 6px;color:#888;border-bottom:1px solid rgba(100,100,100,0.3);margin-bottom:4px;font-size:10px;";
    header.textContent = elements.length + " layers (scroll / arrow keys)";
    panel.appendChild(header);

    this._setupKeyboard(panel);
    this._renderList(panel, elements);
    document.body.appendChild(panel);
    this._panel = panel;
    this.updateSelection();
    setTimeout(function () { panel.focus(); }, 10);
  };

  LayerPickerPanel.prototype._renderList = function (panel, elements) {
    var self = this;
    elements.forEach(function (el, index) {
      var item = document.createElement("div");
      item.dataset.index = String(index);
      item.style.cssText = "padding:5px 10px;cursor:pointer;display:flex;align-items:center;gap:6px;transition:background 0.1s;";

      var depthBar = document.createElement("span");
      var depth = getDepth(el);
      depthBar.style.cssText = "width:" + Math.min(depth * 3, 30) + "px;height:3px;background:" + getColorForDepth(depth) + ";border-radius:2px;flex-shrink:0;";

      var indexNum = document.createElement("span");
      indexNum.style.cssText = "color:#666;width:18px;text-align:right;";
      indexNum.textContent = String(index + 1);

      var info = document.createElement("span");
      var tag = el.tagName.toLowerCase();
      var id = el.id ? "#" + el.id : "";
      var cls = (el.className && typeof el.className === "string") ? "." + el.className.split(" ")[0].substring(0, 15) : "";
      info.innerHTML = '<span style="color:#61afef">' + tag + '</span><span style="color:#e5c07b">' + id + '</span><span style="color:#98c379">' + cls + "</span>";
      info.style.cssText = "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";

      item.appendChild(depthBar);
      item.appendChild(indexNum);
      item.appendChild(info);

      item.addEventListener("mouseenter", function () { item.style.background = "rgba(100,100,100,0.3)"; });
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
            e.preventDefault(); e.stopPropagation();
            self._index = Math.min(self._index + 1, maxIndex);
          } else if (e.key === "Tab") {
            e.preventDefault(); e.stopPropagation();
            self._index = Math.max(self._index - 1, 0);
          }
          if (self._highlightCb) self._highlightCb(self._elements[self._index]);
          self.updateSelection();
          break;
        case "ArrowUp":
          e.preventDefault(); e.stopPropagation();
          self._index = Math.max(self._index - 1, 0);
          if (self._highlightCb) self._highlightCb(self._elements[self._index]);
          self.updateSelection();
          break;
        case "Enter":
          e.preventDefault(); e.stopPropagation();
          self._confirmSelection();
          break;
        case "Escape":
          e.preventDefault(); e.stopPropagation();
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
    navigator.clipboard.writeText(debugInfo).then(function () {
      self._notify.showNotification("Copied!", "success");
      self._notify.triggerCopyCallback();
    }).catch(function (err) {
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
    if (direction === "down") this._index = Math.min(this._index + 1, this._elements.length - 1);
    else this._index = Math.max(this._index - 1, 0);
    if (this._highlightCb) this._highlightCb(this._elements[this._index]);
    this.updateSelection();
  };

  LayerPickerPanel.prototype.remove = function () {
    if (this._panel) { this._panel.remove(); this._panel = null; }
  };

  LayerPickerPanel.prototype.reset = function () {
    this.remove();
    this._elements = [];
    this._index = 0;
  };

  // ── ElementScanner ───────────────────────────────────────────────
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

    this._layerPicker = new LayerPickerPanel(debugCollector, notificationManager);
    this._labelRenderer = new LabelRenderer(debugCollector, notificationManager);

    var self = this;
    this._layerPicker.setHighlightCallback(function (el) {
      if (self._overlayRef) self._highlightElement(el, self._overlayRef);
    });
  }

  ElementScanner.prototype.getElementBoxMap = function () { return this._elementBoxMap; };
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
      if (["script", "style", "link", "meta", "head", "noscript", "br"].indexOf(tagName) !== -1) continue;
      var rect = element.getBoundingClientRect();
      if (rect.width < MIN_SIZE || rect.height < MIN_SIZE) continue;
      if (element instanceof HTMLElement) {
        if (element.offsetParent === null && tagName !== "body" && tagName !== "html") {
          if (element.style.display === "none") continue;
        }
      }
      this._allVisible.push(element);
    }
    var elapsed = (performance.now() - startTime).toFixed(1);
    console.log("[ElementInspector] Found " + this._allVisible.length + " visible elements in " + elapsed + "ms");
  };

  ElementScanner.prototype._renderBatch = function (overlayContainer) {
    var startTime = performance.now();
    var fragment = document.createDocumentFragment();
    var occupiedPositions = [];
    var scrollY = window.scrollY;
    var scrollX = window.scrollX;
    var batchEnd = Math.min(this._batchStart + BATCH_SIZE, this._allVisible.length);
    var count = 0;
    var self = this;

    for (var i = this._batchStart; i < batchEnd; i++) {
      var element = this._allVisible[i];
      var rect = element.getBoundingClientRect();
      var margin = 100;
      if (rect.bottom < -margin || rect.top > window.innerHeight + margin || rect.right < -margin || rect.left > window.innerWidth + margin) continue;

      var depth = getDepth(element);
      var color = getColorForDepth(depth);
      var area = rect.width * rect.height;
      var borderWidth = area > 100000 ? 1 : area > 10000 ? 1.5 : 2;

      var box = document.createElement("div");
      box.className = "element-inspector-box";
      box.style.cssText =
        "top:" + (rect.top + scrollY) + "px;left:" + (rect.left + scrollX) + "px;" +
        "width:" + rect.width + "px;height:" + rect.height + "px;" +
        "border-color:" + color + ";border-width:" + borderWidth + "px;";

      var id = element.id ? "#" + element.id : "";
      box.title = "Right-click to copy | Scroll to cycle depth: " + element.tagName.toLowerCase() + id;

      this._elementBoxMap.set(box, element);

      (function (b, el) {
        b.addEventListener("mouseenter", function () { self._hoveredBox = b; self._hoveredElement = el; });
        b.addEventListener("mouseleave", function () { if (self._hoveredBox === b) { self._hoveredBox = null; self._hoveredElement = null; } });

        b.addEventListener("click", function (e) {
          b.style.pointerEvents = "none";
          var under = document.elementFromPoint(e.clientX, e.clientY);
          b.style.pointerEvents = "";
          if (under && under !== b) {
            var clickEvt = new MouseEvent("click", { bubbles: true, cancelable: true, view: window, clientX: e.clientX, clientY: e.clientY });
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
          navigator.clipboard.writeText(debugInfo).then(function () {
            self._notify.showNotification("Copied!", "success");
            console.log("[ElementInspector] Copied:", debugInfo);
            self._notify.triggerCopyCallback();
          }).catch(function (err) {
            console.error("[ElementInspector] Copy failed:", err);
            self._notify.showNotification("Copy Failed", "error");
            selBox.classList.remove("highlighted");
          });
        });
      })(box, element);

      if (this._labelRenderer.shouldShowLabel(element, rect, depth)) {
        var label = this._labelRenderer.createLabel(element, depth);
        if (label) {
          var labelPos = this._labelRenderer.findLabelPosition(rect, occupiedPositions);
          if (labelPos.isValid) {
            label.style.top = labelPos.top + "px";
            label.style.left = labelPos.left + "px";
            this._labelRenderer.addCopyToClipboard(label, element);
            this._labelRenderer.addHoverHighlight(label, box, element, function (b, e) {
              self._hoveredBox = b;
              self._hoveredElement = e;
            });
            occupiedPositions.push({
              top: labelPos.top - 8, left: labelPos.left - 8,
              bottom: labelPos.top + 20 + 8, right: labelPos.left + 250 + 8,
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
    console.log("[ElementInspector] Rendered " + count + " elements (" + (this._batchStart + 1) + "-" + batchEnd + "/" + total + ") in " + elapsed + "ms" +
      (remaining > 0 ? " | Ctrl+I for next " + Math.min(remaining, BATCH_SIZE) : ""));
    if (remaining > 0) this._notify.showNotification(batchEnd + "/" + total + " elements | Ctrl+I for more", "success", 2000);
  };

  ElementScanner.prototype.loadNextBatch = function () {
    if (!this._overlayRef) return false;
    var total = this._allVisible.length;
    var nextStart = this._batchStart + BATCH_SIZE;
    if (nextStart >= total) { this._notify.showNotification("All elements loaded", "success"); return false; }
    this._batchStart = nextStart;
    this._renderBatch(this._overlayRef);
    return true;
  };

  ElementScanner.prototype._setupWheel = function (overlayContainer) {
    var self = this;
    this._wheelHandler = function (e) {
      if (!overlayContainer.contains(e.target)) return;
      var cursorMoved = Math.abs(e.clientX - self._lastCursorX) > 5 || Math.abs(e.clientY - self._lastCursorY) > 5;
      if (cursorMoved) {
        self._lastCursorX = e.clientX;
        self._lastCursorY = e.clientY;
        var elements = self._getElementsAtPoint(e.clientX, e.clientY);
        self._layerPicker.show(e.clientX, e.clientY, elements);
      }
      var elements = self._layerPicker.getElementsAtCursor();
      if (elements.length <= 1) { self._layerPicker.remove(); return; }
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
      if (["html", "body", "script", "style", "head"].indexOf(tag) !== -1) continue;
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

  ElementScanner.prototype._highlightElement = function (element, overlayContainer) {
    overlayContainer.querySelectorAll(".element-inspector-box.highlighted").forEach(function (box) { box.classList.remove("highlighted"); });
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

  // ── SelectionManager ─────────────────────────────────────────────
  function SelectionManager(elementBoxMap, debugCollector, notificationManager) {
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
    this._onMouseDown = function (e) { self._handleMouseDown(e); };
    this._onMouseMove = function (e) { self._handleMouseMove(e); };
    this._onMouseUp = function (e) { self._handleMouseUp(e); };
  }

  SelectionManager.prototype.setElementScanner = function (scanner) { this._scanner = scanner; };
  SelectionManager.prototype.isActive = function () { return this._selectionMode; };

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
    if (this._overlay) { this._overlay.remove(); this._overlay = null; }
    if (this._rect) { this._rect.remove(); this._rect = null; }
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
    console.log("[ElementInspector] Found " + selectedElements.length + " elements in selection");
    var info = this._gatherSelectionInfo(selectedElements, rect);
    var self = this;
    navigator.clipboard.writeText(info).then(function () {
      self._notify.showNotification(selectedElements.length + " elements copied!", "success");
      self._notify.triggerCopyCallback();
    }).catch(function (err) {
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
      if (element instanceof HTMLElement) element.classList.remove("element-inspector-selected");
    });
    this._selectedElements.clear();
  };

  SelectionManager.prototype._findElementsInRect = function (rect) {
    var selected = [];
    var all = document.querySelectorAll("*");
    var selRect = { left: rect.left, top: rect.top, right: rect.left + rect.width, bottom: rect.top + rect.height };

    var targetDepth = null;
    if (this._scanner) {
      var depthEl = this._scanner.getDepthSelectedElement();
      if (depthEl) targetDepth = getDepth(depthEl);
    }

    for (var i = 0; i < all.length; i++) {
      var element = all[i];
      if (element.closest("#element-inspector-overlay") || element.classList.contains("selection-rectangle") ||
        element.classList.contains("selection-overlay") || element.closest(".element-inspector-layer-picker")) continue;
      var tagName = element.tagName.toLowerCase();
      if (["script", "style", "link", "meta", "head", "noscript", "br", "html", "body"].indexOf(tagName) !== -1) continue;
      if (element instanceof HTMLElement) {
        var computed = window.getComputedStyle(element);
        if (computed.display === "none" || computed.visibility === "hidden") continue;
      }
      if (targetDepth !== null && Math.abs(getDepth(element) - targetDepth) > 2) continue;
      var elRect = element.getBoundingClientRect();
      if (elRect.width < 10 || elRect.height < 10) continue;
      var intersects = !(elRect.right < selRect.left || elRect.left > selRect.right || elRect.bottom < selRect.top || elRect.top > selRect.bottom);
      if (intersects) selected.push(element);
    }
    return selected;
  };

  SelectionManager.prototype._gatherSelectionInfo = function (elements, rect) {
    var info = "# Rectangle Selection Debug Information\n\n" +
      "## Selection Area\n- Position: (" + Math.round(rect.left) + ", " + Math.round(rect.top) + ")\n" +
      "- Size: " + Math.round(rect.width) + "x" + Math.round(rect.height) + "px\n" +
      "- URL: " + window.location.href + "\n- Timestamp: " + new Date().toISOString() +
      "\n- Elements Found: " + elements.length + "\n\n---\n\n";

    var types = {};
    elements.forEach(function (el) {
      var tag = el.tagName.toLowerCase();
      types[tag] = (types[tag] || 0) + 1;
    });
    info += "## Element Type Summary\n";
    Object.entries(types).sort(function (a, b) { return b[1] - a[1]; }).forEach(function (kv) {
      info += "- " + kv[0] + ": " + kv[1] + "\n";
    });
    info += "\n---\n\n";

    var maxDetailed = 20;
    var detailedCount = Math.min(elements.length, maxDetailed);
    info += "## Detailed Element Information (" + detailedCount + " of " + elements.length + " elements)\n\n---\n\n";
    var self = this;
    elements.slice(0, maxDetailed).forEach(function (element, index) {
      info += "# Element " + (index + 1) + "/" + elements.length + "\n\n";
      info += self._debug.gatherElementDebugInfo(element);
      info += "\n" + "=".repeat(80) + "\n\n";
    });

    if (elements.length > maxDetailed) {
      info += "## Remaining Elements (" + (elements.length - maxDetailed) + " elements - basic info)\n\n";
      elements.slice(maxDetailed).forEach(function (element, index) {
        var actualIndex = maxDetailed + index + 1;
        var selector = self._debug.buildCSSSelector(element);
        var r = element.getBoundingClientRect();
        var text = (element.textContent || "").trim().substring(0, 50);
        info += "### " + actualIndex + ". " + selector + "\n";
        info += "- Position: (" + Math.round(r.left) + ", " + Math.round(r.top) + ") | Size: " + Math.round(r.width) + "x" + Math.round(r.height) + "px\n";
        if (text) info += '- Text: "' + text + (text.length > 50 ? "..." : "") + '"\n';
        info += "\n";
      });
    }
    info += "\n---\nGenerated by Element Inspector - Rectangle Selection Mode\n";
    return info;
  };

  // ── ConsoleCollector ─────────────────────────────────────────────
  function ConsoleCollector(notificationManager) {
    this._notify = notificationManager;
    this._logs = [];
    this._networkErrors = [];
    this._maxLogs = 1000;
    this._origConsole = {
      log: console.log.bind(console),
      warn: console.warn.bind(console),
      error: console.error.bind(console),
      info: console.info.bind(console),
      debug: console.debug.bind(console),
    };
    this._startCapturing();
    this._captureNetworkErrors();
  }

  ConsoleCollector.prototype._captureNetworkErrors = function () {
    var self = this;
    window.addEventListener("error", function (e) {
      if (e.target && e.target.tagName) {
        var src = e.target.src || e.target.href || "";
        if (src) self._networkErrors.push("Failed to load resource: " + src);
      }
    }, true);
  };

  ConsoleCollector.prototype._startCapturing = function () {
    var self = this;
    ["log", "warn", "error", "info", "debug"].forEach(function (type) {
      console[type] = function () {
        var args = Array.prototype.slice.call(arguments);
        self._captureLog(type, args);
        self._origConsole[type].apply(console, args);
      };
    });
  };

  ConsoleCollector.prototype._captureLog = function (type, args) {
    this._logs.push({
      type: type,
      timestamp: new Date().toISOString(),
      args: args.map(function (a) {
        if (a === null) return "null";
        if (a === undefined) return "undefined";
        if (typeof a === "string") return a;
        if (typeof a === "number" || typeof a === "boolean") return String(a);
        if (a instanceof Error) return a.name + ": " + a.message + "\n" + (a.stack || "");
        try { return JSON.stringify(a, null, 2); } catch (e) { return String(a); }
      }),
    });
    if (this._logs.length > this._maxLogs) this._logs.shift();
  };

  ConsoleCollector.prototype.getConsoleLogs = function () {
    var total = this._logs.length + this._networkErrors.length;
    if (total === 0) return "No console logs captured.";
    var output = "";
    this._networkErrors.forEach(function (err) { output += "ERROR: " + err + "\n"; });
    this._logs.forEach(function (entry) { output += "[" + entry.type.toUpperCase() + "] " + entry.args.join(" ") + "\n"; });
    return output;
  };

  ConsoleCollector.prototype.captureDebugSnapshot = function () {
    this._notify.showCameraFlash();
    var logsText = this.getConsoleLogs();
    if (!logsText || logsText === "No console logs captured.") {
      this._notify.showNotification("No logs to copy", "error");
      this._notify.triggerCopyCallback();
      return;
    }
    var self = this;
    navigator.clipboard.writeText(logsText).then(function () {
      self._notify.showNotification("Console logs copied!", "success");
      self._notify.triggerCopyCallback();
    }).catch(function (err) {
      self._origConsole.error("[ConsoleCollector] Clipboard failed:", err);
      self._notify.showNotification("Copy Failed", "error");
      self._notify.triggerCopyCallback();
    });
  };

  // ── PageStructureExporter ────────────────────────────────────────
  function PageStructureExporter(notificationManager) {
    this._notify = notificationManager;
  }

  PageStructureExporter.prototype.copyPageStructure = function () {
    console.log("[ElementInspector] Generating full page structure...");
    this._notify.showCameraFlash();
    var structure = this._generate();
    var self = this;
    navigator.clipboard.writeText(structure).then(function () {
      self._notify.showNotification("Page structure copied!", "success");
      self._notify.triggerCopyCallback();
    }).catch(function (err) {
      console.error("[ElementInspector] Failed to copy page structure:", err);
      self._notify.showNotification("Copy Failed", "error");
    });
  };

  PageStructureExporter.prototype._generate = function () {
    var info = {
      url: window.location.href,
      timestamp: new Date().toISOString(),
      viewport: { width: window.innerWidth, height: window.innerHeight, scrollX: window.scrollX, scrollY: window.scrollY },
      document: { title: document.title, readyState: document.readyState },
      structure: this._buildTree(document.body, 0, 10),
    };
    return "# Full Page Structure\n\n## Page Information\n- URL: " + info.url +
      "\n- Title: " + info.document.title + "\n- Timestamp: " + info.timestamp +
      "\n- Viewport: " + info.viewport.width + "x" + info.viewport.height +
      "\n\n## Document Structure\n```json\n" + JSON.stringify(info.structure, null, 2) + "\n```\n";
  };

  PageStructureExporter.prototype._buildTree = function (element, depth, maxDepth) {
    if (depth > maxDepth) return { truncated: true };
    var className = typeof element.className === "string" ? element.className : "";
    var node = { tag: element.tagName.toLowerCase() };
    if (element.id) node.id = element.id;
    if (className) node.classes = className.split(/\s+/).filter(function (c) { return c; });
    var children = [];
    for (var i = 0; i < element.children.length; i++) {
      var child = element.children[i];
      if (child.tagName !== "SCRIPT" && child.tagName !== "STYLE") {
        children.push(this._buildTree(child, depth + 1, maxDepth));
      }
    }
    if (children.length > 0) node.children = children;
    return node;
  };

  // ── ElementInspector (main class) ────────────────────────────────
  function ElementInspector() {
    this._isActive = false;
    this._notifyMgr = new NotificationManager();
    this._debugCollector = new DebugInfoCollector();
    this._overlayMgr = new OverlayManager();
    this._elementScanner = new ElementScanner(this._debugCollector, this._notifyMgr);
    this._selectionMgr = new SelectionManager(this._elementScanner.getElementBoxMap(), this._debugCollector, this._notifyMgr);
    this._selectionMgr.setElementScanner(this._elementScanner);
    this._pageExporter = new PageStructureExporter(this._notifyMgr);
    this._consoleCollector = new ConsoleCollector(this._notifyMgr);

    var self = this;
    this._notifyMgr.setOnCopyCallback(function () { self.deactivate(); });
    this._init();
  }

  ElementInspector.prototype._init = function () {
    var self = this;
    document.addEventListener("keydown", function (e) {
      var key = e.key.toLowerCase();

      // Let navigation keys pass through
      if (["Tab", "Enter", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].indexOf(e.key) !== -1) return;

      // Ctrl+Shift+I: Debug snapshot
      if (e.ctrlKey && e.shiftKey && !e.altKey && key === "i") {
        e.preventDefault(); e.stopPropagation();
        console.log("[ElementInspector] Ctrl+Shift+I pressed - capturing debug snapshot");
        self._consoleCollector.captureDebugSnapshot();
        return;
      }

      // Ctrl+Alt+I: Rectangle selection
      if (e.ctrlKey && e.altKey && !e.shiftKey && key === "i") {
        e.preventDefault();
        self._startSelectionMode();
        return;
      }

      // Ctrl+I: Load next batch (when active)
      if (e.ctrlKey && !e.altKey && !e.shiftKey && key === "i") {
        if (self._isActive) {
          e.preventDefault();
          self._elementScanner.loadNextBatch();
          return;
        }
      }

      // Alt+I: Toggle inspector
      if (e.altKey && !e.shiftKey && !e.ctrlKey && key === "i") {
        e.preventDefault();
        self.toggle();
        return;
      }

      // Escape: Deactivate
      if (e.key === "Escape") {
        if (self._selectionMgr.isActive()) {
          e.preventDefault();
          self._selectionMgr.cancelSelectionMode();
          self.deactivate();
        } else if (self._isActive) {
          e.preventDefault();
          self.deactivate();
        }
        return;
      }
    });

    console.log("[ElementInspector] Initialized");
    console.log("  Alt+I: Toggle inspector overlay");
    console.log("  Ctrl+I: Load next 512 elements (when active)");
    console.log("  Ctrl+Alt+I: Rectangle selection mode");
    console.log("  Ctrl+Shift+I: Debug snapshot (console logs)");
    console.log("  Scroll wheel: Cycle through overlapped elements");
    console.log("  Right-click: Copy element debug info");
    console.log("  Left-click: Pass through to underlying element");
    console.log("  Escape: Deactivate inspector / Cancel selection");
  };

  ElementInspector.prototype.toggle = function () {
    if (this._isActive) this.deactivate();
    else this.activate();
  };

  ElementInspector.prototype.activate = function () {
    console.log("[ElementInspector] Activating...");
    this._isActive = true;
    var container = this._overlayMgr.createOverlay();
    this._elementScanner.scanElements(container);
    console.log("[ElementInspector] Active - Press Alt+I to deactivate");
  };

  ElementInspector.prototype.deactivate = function () {
    console.log("[ElementInspector] Deactivating...");
    this._isActive = false;
    /* Clear any directly-applied outline that wasn't in the box map (#381) */
    this._elementScanner._clearDirectHighlight();
    this._elementScanner.clearElementBoxMap();
    this._overlayMgr.removeOverlay();
  };

  ElementInspector.prototype.refresh = function () {
    if (this._isActive) { this.deactivate(); this.activate(); }
  };

  ElementInspector.prototype._startSelectionMode = function () {
    if (!this._isActive) this.activate();
    this._selectionMgr.startSelectionMode();
  };

  // ── Initialize ───────────────────────────────────────────────────
  var elementInspector = new ElementInspector();
  window.elementInspector = elementInspector;

  var resizeTimeout;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimeout);
    resizeTimeout = window.setTimeout(function () {
      if (window.elementInspector && window.elementInspector._isActive) {
        window.elementInspector.refresh();
      }
    }, 500);
  });
})();
