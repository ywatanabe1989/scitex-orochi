// @ts-nocheck
// Migrated classic-script file. Types intentionally loose during
// the big-bang JS-to-TS bundle migration. Narrow later, per-file.
/* Webcam Capture — live camera feed with multi-photo snapshot for the
 * Orochi composer.
 *
 * Opens a modal overlay with a getUserMedia video stream. "Capture"
 * snapshots a frame to a JPEG blob and hands it to the same pending-
 * attachment staging path the file-attach button uses (stageFiles in
 * upload.js), so the photo lands in the attachment tray and the user
 * can take more photos before pressing Send. "Done" (or ESC / overlay
 * click / Cancel) closes the overlay.
 *
 * Falls back to the hidden <input type="file" accept="image/*"
 * capture="environment"> on getUserMedia failure (user denied / no
 * camera / insecure context) — on mobile browsers this surfaces the
 * native camera UI directly; on desktop it surfaces a normal file
 * picker.
 *
 * Reference impl (TS, single-shot): scitex-cloud
 *   static/shared/ts/components/_global-ai-chat/webcam-capture.ts
 * Ported to vanilla JS and extended with multi-photo + stageFiles
 * handoff for Orochi.
 */
/* globals: stageFiles */

var webcamOverlay = null;
var webcamVideo = null;
var webcamStream = null;
var webcamFacing = "environment";
var webcamCaptureInput = null;
var webcamOnKey = null;

function _webcamEnsureFallbackInput() {
  if (webcamCaptureInput) return webcamCaptureInput;
  webcamCaptureInput = document.getElementById("webcam-capture-input");
  if (webcamCaptureInput) return webcamCaptureInput;
  /* Template did not ship the input — create one programmatically so
   * the fallback path still works. */
  webcamCaptureInput = document.createElement("input");
  webcamCaptureInput.type = "file";
  webcamCaptureInput.accept = "image/*";
  webcamCaptureInput.setAttribute("capture", "environment");
  webcamCaptureInput.id = "webcam-capture-input";
  webcamCaptureInput.style.display = "none";
  document.body.appendChild(webcamCaptureInput);
  return webcamCaptureInput;
}

function _webcamWireFallbackInput() {
  var input = _webcamEnsureFallbackInput();
  if (input._webcamWired) return;
  input._webcamWired = true;
  input.addEventListener("change", function () {
    if (!this.files || this.files.length === 0) return;
    var arr = Array.prototype.slice.call(this.files);
    if (typeof stageFiles === "function") {
      stageFiles(arr);
    } else {
      console.error("[orochi-webcam] stageFiles unavailable");
    }
    this.value = "";
  });
}

function _webcamOpenFallback() {
  var input = _webcamEnsureFallbackInput();
  _webcamWireFallbackInput();
  input.click();
}

async function _webcamRequestStream(facing) {
  return navigator.mediaDevices.getUserMedia({
    video: { facingMode: facing, width: { ideal: 1280 } },
    audio: false,
  });
}

async function openWebcam() {
  if (webcamOverlay) return;
  _webcamWireFallbackInput();

  /* Insecure context / no mediaDevices → straight to file picker.
   * getUserMedia is only exposed on https / localhost. */
  if (
    !navigator.mediaDevices ||
    typeof navigator.mediaDevices.getUserMedia !== "function"
  ) {
    _webcamOpenFallback();
    return;
  }

  try {
    webcamStream = await _webcamRequestStream(webcamFacing);
  } catch (e) {
    /* User denied permission, no camera attached, browser blocked, etc.
     * Fall through to file picker so mobile gets the native camera
     * UI and desktop gets a normal picker. */
    console.warn("[orochi-webcam] getUserMedia failed, falling back:", e);
    _webcamOpenFallback();
    return;
  }

  webcamOverlay = _buildWebcamUI();
  document.body.appendChild(webcamOverlay);
  if (webcamVideo) {
    webcamVideo.srcObject = webcamStream;
  }
}

function _buildWebcamUI() {
  var overlay = document.createElement("div");
  overlay.className = "webcam-overlay";

  var panel = document.createElement("div");
  panel.className = "webcam-panel";
  overlay.appendChild(panel);

  webcamVideo = document.createElement("video");
  webcamVideo.className = "webcam-video";
  webcamVideo.autoplay = true;
  webcamVideo.playsInline = true;
  webcamVideo.muted = true;
  panel.appendChild(webcamVideo);

  var hint = document.createElement("div");
  hint.className = "webcam-hint";
  hint.textContent =
    "Capture adds photo to attachment tray. Done closes the camera.";
  panel.appendChild(hint);

  var actions = document.createElement("div");
  actions.className = "webcam-actions";

  var cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.className = "webcam-btn";
  cancelBtn.textContent = "Cancel";
  cancelBtn.addEventListener("click", closeWebcam);

  var flipBtn = document.createElement("button");
  flipBtn.type = "button";
  flipBtn.className = "webcam-btn";
  flipBtn.textContent = "Flip";
  flipBtn.title = "Switch camera";
  flipBtn.addEventListener("click", flipWebcam);

  var captureBtn = document.createElement("button");
  captureBtn.type = "button";
  captureBtn.className = "webcam-btn webcam-btn-capture";
  captureBtn.textContent = "Capture";
  captureBtn.title = "Take photo";
  captureBtn.addEventListener("click", captureWebcamFrame);

  var doneBtn = document.createElement("button");
  doneBtn.type = "button";
  doneBtn.className = "webcam-btn webcam-btn-primary";
  doneBtn.textContent = "Done";
  doneBtn.title = "Close camera (photos stay in attachment tray)";
  doneBtn.addEventListener("click", closeWebcam);

  actions.append(cancelBtn, flipBtn, captureBtn, doneBtn);
  panel.appendChild(actions);

  overlay.addEventListener("click", function (e) {
    if (e.target === overlay) closeWebcam();
  });

  webcamOnKey = function (e) {
    if (e.key === "Escape") closeWebcam();
  };
  document.addEventListener("keydown", webcamOnKey);

  return overlay;
}

function captureWebcamFrame() {
  if (!webcamVideo || !webcamVideo.videoWidth) return;
  var canvas = document.createElement("canvas");
  canvas.width = webcamVideo.videoWidth;
  canvas.height = webcamVideo.videoHeight;
  var ctx = canvas.getContext("2d");
  ctx.drawImage(webcamVideo, 0, 0, canvas.width, canvas.height);
  canvas.toBlob(
    function (blob) {
      if (!blob) return;
      var ts = new Date()
        .toISOString()
        .replace(/[-:]/g, "")
        .replace(/\..+/, "");
      var filename = "webcam-" + ts + ".jpg";
      /* Wrap blob in File so stageFiles' FormData append behaves
       * exactly like file-picker uploads (keeps filename in multipart
       * form). */
      var file;
      try {
        file = new File([blob], filename, { type: "image/jpeg" });
      } catch (_) {
        /* Safari < 14 sometimes lacks File constructor; fall back to
         * blob with a name shim. */
        blob.name = filename;
        file = blob;
      }
      if (typeof stageFiles === "function") {
        stageFiles([file]);
      } else {
        console.error("[orochi-webcam] stageFiles unavailable");
      }
    },
    "image/jpeg",
    0.9,
  );
}

async function flipWebcam() {
  if (!webcamStream || !webcamVideo) return;
  webcamFacing = webcamFacing === "environment" ? "user" : "environment";
  _webcamStopStream();
  try {
    webcamStream = await _webcamRequestStream(webcamFacing);
    webcamVideo.srcObject = webcamStream;
  } catch (e) {
    /* Only one camera available — revert and try to reacquire original. */
    console.warn("[orochi-webcam] flip failed, reacquiring:", e);
    webcamFacing = webcamFacing === "environment" ? "user" : "environment";
    try {
      webcamStream = await _webcamRequestStream(webcamFacing);
      webcamVideo.srcObject = webcamStream;
    } catch (e2) {
      console.error("[orochi-webcam] could not reacquire stream:", e2);
      closeWebcam();
    }
  }
}

function _webcamStopStream() {
  if (webcamStream) {
    var tracks = webcamStream.getTracks();
    for (var i = 0; i < tracks.length; i++) {
      try {
        tracks[i].stop();
      } catch (_) {}
    }
    webcamStream = null;
  }
}

function closeWebcam() {
  _webcamStopStream();
  if (webcamOverlay) {
    webcamOverlay.remove();
    webcamOverlay = null;
  }
  webcamVideo = null;
  if (webcamOnKey) {
    document.removeEventListener("keydown", webcamOnKey);
    webcamOnKey = null;
  }
}

var _webcamBtn = document.getElementById("msg-webcam");
if (_webcamBtn) {
  _webcamBtn.addEventListener("click", openWebcam);
}
_webcamWireFallbackInput();
