// @ts-nocheck
/**
 * Element Inspector — console collector, page structure exporter, and
 * the top-level ElementInspector class that wires everything together.
 * Loaded last; sets `window.elementInspector`.
 */
(function () {
  "use strict";

  var EI = (window.__EI = window.__EI || {});
  var NotificationManager = EI.NotificationManager;
  var DebugInfoCollector = EI.DebugInfoCollector;
  var OverlayManager = EI.OverlayManager;
  var ElementScanner = EI.ElementScanner;
  var SelectionManager = EI.SelectionManager;

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
    window.addEventListener(
      "error",
      function (e) {
        if (e.target && e.target.tagName) {
          var src = e.target.src || e.target.href || "";
          if (src) self._networkErrors.push("Failed to load resource: " + src);
        }
      },
      true,
    );
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
        if (a instanceof Error)
          return a.name + ": " + a.message + "\n" + (a.stack || "");
        try {
          return JSON.stringify(a, null, 2);
        } catch (e) {
          return String(a);
        }
      }),
    });
    if (this._logs.length > this._maxLogs) this._logs.shift();
  };

  ConsoleCollector.prototype.getConsoleLogs = function () {
    var total = this._logs.length + this._networkErrors.length;
    if (total === 0) return "No console logs captured.";
    var output = "";
    this._networkErrors.forEach(function (err) {
      output += "ERROR: " + err + "\n";
    });
    this._logs.forEach(function (entry) {
      output +=
        "[" + entry.type.toUpperCase() + "] " + entry.args.join(" ") + "\n";
    });
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
    navigator.clipboard
      .writeText(logsText)
      .then(function () {
        self._notify.showNotification("Console logs copied!", "success");
        self._notify.triggerCopyCallback();
      })
      .catch(function (err) {
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
    navigator.clipboard
      .writeText(structure)
      .then(function () {
        self._notify.showNotification("Page structure copied!", "success");
        self._notify.triggerCopyCallback();
      })
      .catch(function (err) {
        console.error("[ElementInspector] Failed to copy page structure:", err);
        self._notify.showNotification("Copy Failed", "error");
      });
  };

  PageStructureExporter.prototype._generate = function () {
    var info = {
      url: window.location.href,
      timestamp: new Date().toISOString(),
      viewport: {
        width: window.innerWidth,
        height: window.innerHeight,
        scrollX: window.scrollX,
        scrollY: window.scrollY,
      },
      document: { title: document.title, readyState: document.readyState },
      structure: this._buildTree(document.body, 0, 10),
    };
    return (
      "# Full Page Structure\n\n## Page Information\n- URL: " +
      info.url +
      "\n- Title: " +
      info.document.title +
      "\n- Timestamp: " +
      info.timestamp +
      "\n- Viewport: " +
      info.viewport.width +
      "x" +
      info.viewport.height +
      "\n\n## Document Structure\n```json\n" +
      JSON.stringify(info.structure, null, 2) +
      "\n```\n"
    );
  };

  PageStructureExporter.prototype._buildTree = function (
    element,
    depth,
    maxDepth,
  ) {
    if (depth > maxDepth) return { truncated: true };
    var className =
      typeof element.className === "string" ? element.className : "";
    var node = { tag: element.tagName.toLowerCase() };
    if (element.id) node.id = element.id;
    if (className)
      node.classes = className.split(/\s+/).filter(function (c) {
        return c;
      });
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
    this._elementScanner = new ElementScanner(
      this._debugCollector,
      this._notifyMgr,
    );
    this._selectionMgr = new SelectionManager(
      this._elementScanner.getElementBoxMap(),
      this._debugCollector,
      this._notifyMgr,
    );
    this._selectionMgr.setElementScanner(this._elementScanner);
    this._pageExporter = new PageStructureExporter(this._notifyMgr);
    this._consoleCollector = new ConsoleCollector(this._notifyMgr);

    var self = this;
    this._notifyMgr.setOnCopyCallback(function () {
      self.deactivate();
    });
    this._init();
  }

  ElementInspector.prototype._init = function () {
    var self = this;
    document.addEventListener("keydown", function (e) {
      var key = e.key.toLowerCase();

      // Let navigation keys pass through
      if (
        [
          "Tab",
          "Enter",
          "ArrowUp",
          "ArrowDown",
          "ArrowLeft",
          "ArrowRight",
        ].indexOf(e.key) !== -1
      )
        return;

      // Ctrl+Shift+I: Debug snapshot
      if (e.ctrlKey && e.shiftKey && !e.altKey && key === "i") {
        e.preventDefault();
        e.stopPropagation();
        console.log(
          "[ElementInspector] Ctrl+Shift+I pressed - capturing debug snapshot",
        );
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
    if (this._isActive) {
      this.deactivate();
      this.activate();
    }
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

// Auto-generated module re-exports for symbols assigned to `window`
// inside the file-level IIFE above. These run after the IIFE's side
// effects so other ES modules can import these names instead of
// reaching into `window`.
export const elementInspector = (window as any).elementInspector;
