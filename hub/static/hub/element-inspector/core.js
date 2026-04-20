/**
 * Element Inspector — core utilities, notifications, debug-info collector,
 * overlay manager, and label renderer.
 *
 * Loaded first; companion files picker-scanner.js and main.js depend on the
 * symbols exported on `window.__EI` here. See element-inspector.js (deleted)
 * header comment in git history for the full feature description.
 */
(function () {
  "use strict";

  var EI = (window.__EI = window.__EI || {});

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

  EI.getDepth = getDepth;
  EI.getColorForDepth = getColorForDepth;
  EI.hexToRgba = hexToRgba;

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

  NotificationManager.prototype.showNotification = function (
    message,
    type,
    duration,
  ) {
    duration = duration || 1000;
    var el = document.createElement("div");
    el.textContent = message;
    el.style.cssText =
      "position:fixed;top:16px;right:16px;padding:10px 20px;" +
      "background:" +
      (type === "success" ? "rgba(16,185,129,0.95)" : "rgba(239,68,68,0.95)") +
      ";" +
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
      setTimeout(function () {
        el.remove();
      }, 200);
    }, duration);
  };

  NotificationManager.prototype.showCameraFlash = function () {
    var flash = document.createElement("div");
    flash.style.cssText =
      "position:fixed;top:0;left:0;right:0;bottom:0;" +
      "background:rgba(255,255,255,0.4);z-index:9999999;" +
      "pointer-events:none;opacity:1;transition:opacity 0.1s ease;";
    document.body.appendChild(flash);
    setTimeout(function () {
      flash.style.opacity = "0";
    }, 30);
    setTimeout(function () {
      flash.remove();
    }, 130);
  };

  EI.NotificationManager = NotificationManager;

  // ── DebugInfoCollector ───────────────────────────────────────────
  function DebugInfoCollector() {}

  DebugInfoCollector.prototype.buildCSSSelector = function (element) {
    var tag = element.tagName.toLowerCase();
    var id = element.id;
    var classes = element.className;
    var selector = tag;
    if (id) selector += "#" + id;
    if (classes && typeof classes === "string") {
      var classList = classes.split(/\s+/).filter(function (c) {
        return c;
      });
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
        if (
          sibling.nodeType === Node.ELEMENT_NODE &&
          sibling.nodeName === current.nodeName
        )
          index++;
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
    var eventAttrs = [
      "onclick",
      "onload",
      "onchange",
      "onsubmit",
      "onmouseover",
      "onmouseout",
    ];
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
                  cssText:
                    rule.cssText.substring(0, 200) +
                    (rule.cssText.length > 200 ? "..." : ""),
                  source: sheet.href || "<inline style>",
                  ruleIndex: j,
                });
              }
            } catch (e) {
              /* invalid selector */
            }
          }
        }
      } catch (e) {
        /* CORS */
      }
    }
    return matchingRules;
  };

  DebugInfoCollector.prototype.gatherElementDebugInfo = function (element) {
    var info = {};
    info.url = window.location.href;
    info.timestamp = new Date().toISOString();

    var className =
      typeof element.className === "string" ? element.className : "";
    info.element = {
      tag: element.tagName.toLowerCase(),
      id: element.id || null,
      classes: className
        ? className.split(/\s+/).filter(function (c) {
            return c;
          })
        : [],
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
        display: computed.display,
        position: computed.position,
        width: computed.width,
        height: computed.height,
        margin: computed.margin,
        padding: computed.padding,
        backgroundColor: computed.backgroundColor,
        color: computed.color,
        fontSize: computed.fontSize,
        fontFamily: computed.fontFamily,
        zIndex: computed.zIndex,
        opacity: computed.opacity,
        visibility: computed.visibility,
        overflow: computed.overflow,
      };
      if (element.style.cssText) info.inlineStyles = element.style.cssText;
      var rect = element.getBoundingClientRect();
      info.dimensions = {
        width: rect.width,
        height: rect.height,
        top: rect.top,
        left: rect.left,
        bottom: rect.bottom,
        right: rect.right,
      };
      info.scroll = {
        scrollTop: element.scrollTop,
        scrollLeft: element.scrollLeft,
        scrollHeight: element.scrollHeight,
        scrollWidth: element.scrollWidth,
      };
      info.content = {
        innerHTML:
          element.innerHTML.substring(0, 200) +
          (element.innerHTML.length > 200 ? "..." : ""),
        textContent:
          (element.textContent || "").substring(0, 200) +
          ((element.textContent || "").length > 200 ? "..." : ""),
      };
    }

    info.eventListeners = this._getEventListeners(element);
    info.parentChain = this._getParentChain(element);
    info.appliedStylesheets = this._getAppliedStylesheets();
    info.matchingCSSRules = this._getMatchingCSSRules(element);

    return this._formatDebugInfoForAI(info);
  };

  DebugInfoCollector.prototype._formatDebugInfoForAI = function (info) {
    var attrs = Object.entries(info.attributes || {})
      .map(function (kv) {
        return "- " + kv[0] + ": " + kv[1];
      })
      .join("\n");
    var styles = Object.entries(info.styles || {})
      .map(function (kv) {
        return "- " + kv[0] + ": " + kv[1];
      })
      .join("\n");
    var listeners =
      info.eventListeners && info.eventListeners.length > 0
        ? info.eventListeners.join(", ")
        : "none detected";
    var parents = (info.parentChain || [])
      .map(function (p, i) {
        return i + 1 + ". " + p;
      })
      .join("\n");
    var sheets = (info.appliedStylesheets || [])
      .slice(0, 10)
      .map(function (s, i) {
        return i + 1 + ". " + s;
      })
      .join("\n");
    var rulesCount = (info.matchingCSSRules || []).length;
    var rulesText =
      rulesCount > 0
        ? info.matchingCSSRules
            .slice(0, 10)
            .map(function (rule, i) {
              return (
                "\n### " +
                (i + 1) +
                ". " +
                rule.selector +
                "\n- Source: " +
                rule.source +
                "\n- Rule Index: " +
                rule.ruleIndex +
                "\n- CSS: " +
                rule.cssText +
                "\n"
              );
            })
            .join("\n")
        : "No matching rules found (may be due to CORS restrictions)";

    return (
      "# Element Debug Information\n\n" +
      "## Page Context\n- URL: " +
      info.url +
      "\n- Timestamp: " +
      info.timestamp +
      "\n\n" +
      "## Element Identification\n- Tag: <" +
      info.element.tag +
      ">\n- ID: " +
      (info.element.id || "none") +
      "\n- Classes: " +
      (info.element.classes.join(", ") || "none") +
      "\n- CSS Selector: " +
      info.element.selector +
      "\n- XPath: " +
      info.element.xpath +
      "\n\n" +
      "## Attributes\n" +
      (attrs || "none") +
      "\n\n" +
      "## Computed Styles\n" +
      (styles || "none") +
      "\n\n" +
      (info.inlineStyles
        ? "## Inline Styles\n" + info.inlineStyles + "\n\n"
        : "") +
      "## Dimensions & Position\n- Width: " +
      (info.dimensions ? info.dimensions.width : "?") +
      "px\n" +
      "- Height: " +
      (info.dimensions ? info.dimensions.height : "?") +
      "px\n" +
      "- Top: " +
      (info.dimensions ? info.dimensions.top : "?") +
      "px\n" +
      "- Left: " +
      (info.dimensions ? info.dimensions.left : "?") +
      "px\n\n" +
      "## Scroll State\n- scrollTop: " +
      (info.scroll ? info.scroll.scrollTop : "?") +
      "\n- scrollLeft: " +
      (info.scroll ? info.scroll.scrollLeft : "?") +
      "\n\n" +
      "## Content (truncated)\n" +
      (info.content ? info.content.textContent : "none") +
      "\n\n" +
      "## Event Listeners\n" +
      listeners +
      "\n\n" +
      "## Parent Chain\n" +
      parents +
      "\n\n" +
      "## Applied Stylesheets\n" +
      sheets +
      "\n\n" +
      "## Matching CSS Rules (" +
      rulesCount +
      " rules)\n" +
      rulesText +
      "\n\n" +
      "---\nThis debug information was captured by Element Inspector.\n"
    );
  };

  EI.DebugInfoCollector = DebugInfoCollector;
})();
