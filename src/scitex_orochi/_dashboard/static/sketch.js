/* Sketch Canvas -- freehand drawing tool */
/* globals: escapeHtml, currentChannel, userName, sendOrochiMessage, token */

var sketchOverlay = null;
var sketchCanvas = null;
var sketchCtx = null;
var sketchDrawing = false;
var sketchTool = "pen";
var sketchColor = "#ffffff";
var sketchLineWidth = 5;
var SKETCH_COLORS = [
  "#ffffff",
  "#ef4444",
  "#f59e0b",
  "#22c55e",
  "#3b82f6",
  "#8b5cf6",
  "#ec4899",
  "#6b7280",
];
var SKETCH_WIDTHS = [2, 5, 10];
var SKETCH_WIDTH_LABELS = ["Thin", "Med", "Thick"];

function openSketch() {
  if (sketchOverlay) return;
  sketchOverlay = document.createElement("div");
  sketchOverlay.className = "sketch-overlay";
  var panel = document.createElement("div");
  panel.className = "sketch-panel";
  sketchOverlay.appendChild(panel);
  var toolbar = document.createElement("div");
  toolbar.className = "sketch-toolbar";
  panel.appendChild(toolbar);
  var penBtn = document.createElement("button");
  penBtn.className = "sketch-tool-btn active";
  penBtn.textContent = "Pen";
  penBtn.addEventListener("click", function () {
    sketchTool = "pen";
    toolbar.querySelectorAll(".sketch-tool-btn").forEach(function (b) {
      b.classList.remove("active");
    });
    penBtn.classList.add("active");
  });
  toolbar.appendChild(penBtn);
  var eraserBtn = document.createElement("button");
  eraserBtn.className = "sketch-tool-btn";
  eraserBtn.textContent = "Eraser";
  eraserBtn.addEventListener("click", function () {
    sketchTool = "eraser";
    toolbar.querySelectorAll(".sketch-tool-btn").forEach(function (b) {
      b.classList.remove("active");
    });
    eraserBtn.classList.add("active");
  });
  toolbar.appendChild(eraserBtn);
  var sep1 = document.createElement("span");
  sep1.className = "sketch-sep";
  toolbar.appendChild(sep1);
  SKETCH_COLORS.forEach(function (c) {
    var swatch = document.createElement("button");
    swatch.className = "sketch-color" + (c === sketchColor ? " active" : "");
    swatch.style.background = c;
    swatch.addEventListener("click", function () {
      toolbar.querySelectorAll(".sketch-color").forEach(function (s) {
        s.classList.remove("active");
      });
      swatch.classList.add("active");
      sketchColor = c;
      sketchTool = "pen";
      toolbar.querySelectorAll(".sketch-tool-btn").forEach(function (b) {
        b.classList.toggle("active", b.textContent === "Pen");
      });
    });
    toolbar.appendChild(swatch);
  });
  var sep2 = document.createElement("span");
  sep2.className = "sketch-sep";
  toolbar.appendChild(sep2);
  SKETCH_WIDTHS.forEach(function (w, i) {
    var btn = document.createElement("button");
    btn.className =
      "sketch-width-btn" + (w === sketchLineWidth ? " active" : "");
    btn.textContent = SKETCH_WIDTH_LABELS[i];
    btn.addEventListener("click", function () {
      toolbar.querySelectorAll(".sketch-width-btn").forEach(function (b) {
        b.classList.remove("active");
      });
      btn.classList.add("active");
      sketchLineWidth = w;
    });
    toolbar.appendChild(btn);
  });
  sketchCanvas = document.createElement("canvas");
  sketchCanvas.className = "sketch-canvas";
  sketchCanvas.width = 1200;
  sketchCanvas.height = 800;
  panel.appendChild(sketchCanvas);
  sketchCtx = sketchCanvas.getContext("2d");
  sketchCtx.fillStyle = "#1a1a2e";
  sketchCtx.fillRect(0, 0, 1200, 800);
  sketchCanvas.style.touchAction = "none";
  sketchCanvas.addEventListener("pointerdown", function (e) {
    sketchDrawing = true;
    sketchCtx.beginPath();
    var r = sketchCanvas.getBoundingClientRect();
    sketchCtx.moveTo(
      ((e.clientX - r.left) / r.width) * 1200,
      ((e.clientY - r.top) / r.height) * 800,
    );
  });
  sketchCanvas.addEventListener("pointermove", function (e) {
    if (!sketchDrawing) return;
    var r = sketchCanvas.getBoundingClientRect();
    var x = ((e.clientX - r.left) / r.width) * 1200;
    var y = ((e.clientY - r.top) / r.height) * 800;
    sketchCtx.lineWidth = sketchLineWidth;
    sketchCtx.lineCap = "round";
    sketchCtx.lineJoin = "round";
    if (sketchTool === "eraser") {
      sketchCtx.globalCompositeOperation = "destination-out";
      sketchCtx.strokeStyle = "rgba(0,0,0,1)";
    } else {
      sketchCtx.globalCompositeOperation = "source-over";
      sketchCtx.strokeStyle = sketchColor;
    }
    sketchCtx.lineTo(x, y);
    sketchCtx.stroke();
    sketchCtx.beginPath();
    sketchCtx.moveTo(x, y);
  });
  sketchCanvas.addEventListener("pointerup", function () {
    sketchDrawing = false;
  });
  sketchCanvas.addEventListener("pointerleave", function () {
    sketchDrawing = false;
  });
  var actions = document.createElement("div");
  actions.className = "sketch-actions";
  var clearBtn = document.createElement("button");
  clearBtn.className = "sketch-btn";
  clearBtn.textContent = "Clear";
  clearBtn.addEventListener("click", function () {
    sketchCtx.globalCompositeOperation = "source-over";
    sketchCtx.fillStyle = "#1a1a2e";
    sketchCtx.fillRect(0, 0, 1200, 800);
  });
  var cancelBtn = document.createElement("button");
  cancelBtn.className = "sketch-btn";
  cancelBtn.textContent = "Cancel";
  cancelBtn.addEventListener("click", closeSketch);
  var sendBtn = document.createElement("button");
  sendBtn.className = "sketch-btn sketch-btn-primary";
  sendBtn.textContent = "Send";
  sendBtn.addEventListener("click", sendSketch);
  actions.append(clearBtn, cancelBtn, sendBtn);
  panel.appendChild(actions);
  sketchOverlay.addEventListener("click", function (e) {
    if (e.target === sketchOverlay) closeSketch();
  });
  var onKey = function (e) {
    if (e.key === "Escape") {
      closeSketch();
      document.removeEventListener("keydown", onKey);
    }
  };
  document.addEventListener("keydown", onKey);
  document.body.appendChild(sketchOverlay);
}

function closeSketch() {
  if (sketchOverlay) {
    sketchOverlay.remove();
    sketchOverlay = null;
    sketchCanvas = null;
    sketchCtx = null;
  }
}

async function sendSketch() {
  if (!sketchCanvas) return;
  var dataUrl = sketchCanvas.toDataURL("image/png");
  var b64 = dataUrl.split(",")[1];
  closeSketch();
  try {
    var res = await fetch("/api/upload-base64?token=" + token, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        data: b64,
        filename: "sketch.png",
        mime_type: "image/png",
      }),
    });
    if (!res.ok) {
      console.error("Sketch upload failed:", res.status);
      return;
    }
    var result = await res.json();
    var channel = currentChannel || "#general";
    sendOrochiMessage({
      type: "message",
      sender: userName,
      payload: {
        channel: channel,
        content: "sketch",
        attachments: [result],
      },
    });
  } catch (e) {
    console.error("Sketch upload error:", e);
  }
}

document.getElementById("msg-sketch").addEventListener("click", openSketch);
