/* activity-tab/seekbar.js — timeline seekbar + engagement heatmap
 * + play/pause + live/playback toggle for packet replay. */


/* ---------- todo#67 — Seekbar + play button (packet replay) ----------
 *
 * The topology SVG is live by default. The seekbar at the bottom of
 * `.topo-wrap` shows the last TOPO_SEEK_WINDOW_MS (5 min) of recorded
 * pulses. Dragging the slider puts the view into playback mode — live
 * pulses are suppressed in _topoPulseEdge so the canvas doesn't fight
 * the scrubbed timeline. Play steps the playhead forward in real time
 * (or sped up) and replays each event that crosses the head. Hitting
 * end-of-buffer, or clicking the "live" chip, returns to live mode.
 *
 * All listeners are delegated from the grid (the stable parent) because
 * _renderActivityTopology rewrites the `.topo-wrap` innerHTML on every
 * heartbeat — per-element bindings would be lost.
 * ----------------------------------------------------------------- */

function _topoSeekbarHtml() {
  var mode = _topoSeekMode;
  var playing = _topoSeekPlaying;
  var playGlyph = playing ? "❚❚" : "▶";
  var playTitle = playing ? "Pause" : "Play";
  var liveCls =
    "topo-seek-live" + (mode === "live" ? " topo-seek-live-on" : "");
  /* Slider runs 0..1000 (permill of window). Actual ts is resolved in
   * _topoSeekUpdateUI using the live buffer start/end.
   * todo#97 — The .topo-seek-track-wrap groups the heatmap <canvas> and
   * the <input type=range> so the density bar stays pixel-aligned with
   * the scrubber track regardless of flex sizing. */
  return (
    '<div class="topo-seekbar" role="group" aria-label="Timeline scrubber">' +
    '<button type="button" class="topo-seek-btn topo-seek-play" ' +
    'data-topo-seek="toggle-play" title="' +
    playTitle +
    '">' +
    playGlyph +
    "</button>" +
    '<button type="button" class="' +
    liveCls +
    '" data-topo-seek="live" title="Jump to live">LIVE</button>' +
    '<div class="topo-seek-track-wrap">' +
    '<canvas class="topo-seek-heatmap" ' +
    'data-topo-seek="heatmap" aria-hidden="true"></canvas>' +
    '<input type="range" class="topo-seek-range" ' +
    'min="0" max="1000" step="1" value="1000" ' +
    'data-topo-seek="range" aria-label="Timeline position"/>' +
    "</div>" +
    '<span class="topo-seek-label" data-topo-seek="label">—</span>' +
    "</div>"
  );
}

/* todo#97 — Engagement density heatmap on the seekbar track.
 * Bins _topoSeekEvents into TOPO_SEEK_HEAT_BINS buckets across the same
 * [start, end] window the slider spans, then paints each bucket as a
 * vertical column on the heatmap canvas with intensity proportional to
 * the bucket count. The painted image is cached and only recomputed
 * when the event buffer length or the buffer window edges change, and
 * at most once per TOPO_SEEK_HEAT_THROTTLE_MS. */

function _topoSeekHeatColor(intensity) {
  /* Viridis-like 5-stop ramp (dark purple -> teal -> yellow). intensity
   * in [0, 1]; returns an rgba string with alpha that grows with the
   * bucket count so empty bins fade into the track background. */
  if (intensity <= 0) return "rgba(0,0,0,0)";
  var i = Math.max(0, Math.min(1, intensity));
  var stops = [
    [68, 1, 84] /* 0.00 deep purple */,
    [59, 82, 139] /* 0.25 blue */,
    [33, 144, 141] /* 0.50 teal */,
    [94, 201, 98] /* 0.75 green */,
    [253, 231, 37] /* 1.00 yellow */,
  ];
  var f = i * (stops.length - 1);
  var lo = Math.floor(f);
  var hi = Math.min(stops.length - 1, lo + 1);
  var t = f - lo;
  var r = Math.round(stops[lo][0] + (stops[hi][0] - stops[lo][0]) * t);
  var g = Math.round(stops[lo][1] + (stops[hi][1] - stops[lo][1]) * t);
  var b = Math.round(stops[lo][2] + (stops[hi][2] - stops[lo][2]) * t);
  /* Alpha ramps in so near-empty bins don't smear across the track. */
  var a = 0.35 + 0.55 * i;
  return "rgba(" + r + "," + g + "," + b + "," + a.toFixed(3) + ")";
}

function _topoSeekHeatCompute(winStart, winEnd, bins) {
  var n = _topoSeekEvents.length;
  var out = new Array(bins);
  for (var k = 0; k < bins; k++) out[k] = 0;
  if (!n || winEnd <= winStart) return { counts: out, max: 0 };
  var span = winEnd - winStart;
  var max = 0;
  for (var j = 0; j < n; j++) {
    var ts = _topoSeekEvents[j].ts;
    if (ts < winStart || ts > winEnd) continue;
    var rel = (ts - winStart) / span;
    var idx = Math.min(bins - 1, Math.max(0, Math.floor(rel * bins)));
    out[idx] += 1;
    if (out[idx] > max) max = out[idx];
  }
  return { counts: out, max: max };
}

function _topoSeekHeatPaint(canvas, force) {
  if (!canvas) return;
  var now =
    typeof performance !== "undefined" && performance.now
      ? performance.now()
      : Date.now();
  if (!force && now - _topoSeekHeatLastPaint < TOPO_SEEK_HEAT_THROTTLE_MS) {
    return;
  }
  var w = _topoSeekBuffer();
  /* Signature short-circuits wasted repaints — length + window edges
   * fully determine the histogram, so if nothing changed we skip. */
  var sig = _topoSeekEvents.length + ":" + w.start + ":" + w.end;
  if (!force && sig === _topoSeekHeatLastSig) return;
  _topoSeekHeatLastSig = sig;
  _topoSeekHeatLastPaint = now;
  var rect = canvas.getBoundingClientRect();
  var cssW = Math.max(1, Math.round(rect.width));
  var cssH = Math.max(1, Math.round(rect.height));
  var dpr = window.devicePixelRatio || 1;
  /* Only resize the backing store when the CSS size changes, to avoid
   * clearing + re-scaling on every heartbeat. */
  var targetW = Math.round(cssW * dpr);
  var targetH = Math.round(cssH * dpr);
  if (canvas.width !== targetW || canvas.height !== targetH) {
    canvas.width = targetW;
    canvas.height = targetH;
  }
  var ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);
  var hist = _topoSeekHeatCompute(w.start, w.end, TOPO_SEEK_HEAT_BINS);
  if (!hist.max) return;
  /* Sqrt-scaled intensity so a handful of active bins don't wash out
   * neighbouring low-activity ones. */
  var colW = cssW / TOPO_SEEK_HEAT_BINS;
  for (var k = 0; k < TOPO_SEEK_HEAT_BINS; k++) {
    var c = hist.counts[k];
    if (!c) continue;
    var intensity = Math.sqrt(c / hist.max);
    ctx.fillStyle = _topoSeekHeatColor(intensity);
    /* +1 on width hides sub-pixel seams between adjacent columns. */
    ctx.fillRect(Math.floor(k * colW), 0, Math.ceil(colW) + 1, cssH);
  }
}

function _topoSeekHeatRefresh(force) {
  var bar = document.querySelector(".activity-view-topology .topo-seekbar");
  if (!bar) return;
  var canvas = bar.querySelector('[data-topo-seek="heatmap"]');
  _topoSeekHeatPaint(canvas, !!force);
}

function _topoSeekBuffer() {
  /* Returns {start, end} unix-ms bracketing the usable playback window.
   * Falls back to "now" when empty so the UI has something to render. */
  var n = _topoSeekEvents.length;
  var now = Date.now();
  if (!n) return { start: now - TOPO_SEEK_WINDOW_MS, end: now };
  return {
    start: _topoSeekEvents[0].ts,
    end: Math.max(now, _topoSeekEvents[n - 1].ts),
  };
}

function _topoSeekFormatLabel(ts, mode) {
  if (mode === "live") return "live";
  var d = new Date(ts);
  var hh = String(d.getHours()).padStart(2, "0");
  var mm = String(d.getMinutes()).padStart(2, "0");
  var ss = String(d.getSeconds()).padStart(2, "0");
  var deltaSec = Math.max(0, Math.round((Date.now() - ts) / 1000));
  var ago;
  if (deltaSec < 60) ago = deltaSec + "s ago";
  else ago = Math.floor(deltaSec / 60) + "m" + (deltaSec % 60) + "s ago";
  return hh + ":" + mm + ":" + ss + " (" + ago + ")";
}

function _topoSeekUpdateUI() {
  var bar = document.querySelector(".activity-view-topology .topo-seekbar");
  if (!bar) return;
  var range = bar.querySelector('[data-topo-seek="range"]');
  var label = bar.querySelector('[data-topo-seek="label"]');
  var live = bar.querySelector('[data-topo-seek="live"]');
  var play =
    bar.querySelector('[data-topo-seek="play"]') ||
    bar.querySelector(".topo-seek-play");
  var w = _topoSeekBuffer();
  var span = Math.max(1, w.end - w.start);
  if (_topoSeekMode === "live") {
    /* Live mode: slider head glued to max (1000); label shows "live". */
    if (range && !_topoSeekInteracting) range.value = "1000";
    if (label) label.textContent = _topoSeekFormatLabel(w.end, "live");
    if (live) live.classList.add("topo-seek-live-on");
    bar.classList.remove("topo-seek-playback");
  } else {
    if (range && !_topoSeekInteracting) {
      var permill = Math.round(((_topoSeekTime - w.start) / span) * 1000);
      range.value = String(Math.max(0, Math.min(1000, permill)));
    }
    if (label)
      label.textContent = _topoSeekFormatLabel(_topoSeekTime, "playback");
    if (live) live.classList.remove("topo-seek-live-on");
    bar.classList.add("topo-seek-playback");
  }
  if (play) {
    play.textContent = _topoSeekPlaying ? "❚❚" : "▶";
    play.title = _topoSeekPlaying ? "Pause" : "Play";
  }
  /* todo#97 — Keep the engagement heatmap in lockstep with every UI
   * refresh. _topoSeekHeatPaint internally throttles + short-circuits
   * when nothing meaningful changed, so calling it from every update
   * is cheap. */
  var canvas = bar.querySelector('[data-topo-seek="heatmap"]');
  if (canvas) _topoSeekHeatPaint(canvas, false);
}

function _topoSeekEnterPlayback(ts) {
  _topoSeekMode = "playback";
  _topoSeekTime = ts;
}

function _topoSeekEnterLive() {
  _topoSeekMode = "live";
  _topoSeekStopPlay();
  _topoSeekUpdateUI();
}

function _topoSeekReplayOne(ev) {
  /* Re-invoke _topoPulseEdge for a historical event, with the replay
   * guard flipped on so it doesn't double-record into the buffer and so
   * the "suppress during playback" gate lets it through. */
  _topoSeekReplayInProgress = true;
  try {
    _topoPulseEdge(ev.sender, ev.channel, ev.opts);
  } finally {
    _topoSeekReplayInProgress = false;
  }
}

function _topoSeekStartPlay() {
  if (_topoSeekPlaying) return;
  /* If currently in live mode, snap playhead to start-of-buffer so
   * pressing play from the live view replays the whole window. */
  if (_topoSeekMode === "live") {
    var w0 = _topoSeekBuffer();
    _topoSeekEnterPlayback(w0.start);
  }
  _topoSeekPlaying = true;
  _topoSeekLastFrameTs = 0;
  function _tick(now) {
    if (!_topoSeekPlaying) return;
    if (!_topoSeekLastFrameTs) _topoSeekLastFrameTs = now;
    var dt = (now - _topoSeekLastFrameTs) * _topoSeekSpeed;
    _topoSeekLastFrameTs = now;
    var prev = _topoSeekTime;
    _topoSeekTime += dt;
    var w = _topoSeekBuffer();
    /* Fire every event that crossed the playhead in this frame. */
    for (var i = 0; i < _topoSeekEvents.length; i++) {
      var ev = _topoSeekEvents[i];
      if (ev.ts > prev && ev.ts <= _topoSeekTime) {
        _topoSeekReplayOne(ev);
      }
    }
    if (_topoSeekTime >= w.end) {
      /* Reached the live edge — auto-return to live mode. */
      _topoSeekStopPlay();
      _topoSeekEnterLive();
      return;
    }
    _topoSeekUpdateUI();
    _topoSeekRafId = requestAnimationFrame(_tick);
  }
  _topoSeekRafId = requestAnimationFrame(_tick);
  _topoSeekUpdateUI();
}

function _topoSeekStopPlay() {
  _topoSeekPlaying = false;
  if (_topoSeekRafId != null) {
    cancelAnimationFrame(_topoSeekRafId);
    _topoSeekRafId = null;
  }
  _topoSeekUpdateUI();
}

function _topoSeekTogglePlay() {
  if (_topoSeekPlaying) _topoSeekStopPlay();
  else _topoSeekStartPlay();
}

function _wireTopoSeekbar(grid) {
  if (_topoSeekWired || !grid) return;
  _topoSeekWired = true;
  /* Delegated click for buttons. */
  grid.addEventListener("click", function (ev) {
    var t = ev.target.closest && ev.target.closest("[data-topo-seek]");
    if (!t) return;
    if (!grid.contains(t)) return;
    var act = t.getAttribute("data-topo-seek");
    if (act === "toggle-play") {
      _topoSeekTogglePlay();
    } else if (act === "live") {
      _topoSeekEnterLive();
    }
  });
  /* Delegated range input — scrub = enter playback, update playhead. */
  grid.addEventListener("input", function (ev) {
    var t = ev.target;
    if (!t || t.getAttribute("data-topo-seek") !== "range") return;
    _topoSeekInteracting = true;
    var w = _topoSeekBuffer();
    var permill = Number(t.value) || 0;
    var ts = w.start + ((w.end - w.start) * permill) / 1000;
    /* Dragging to the far right returns to live mode; otherwise playback. */
    if (permill >= 999) {
      _topoSeekEnterLive();
    } else {
      _topoSeekStopPlay();
      _topoSeekEnterPlayback(ts);
    }
    _topoSeekUpdateUI();
  });
  grid.addEventListener("change", function (ev) {
    var t = ev.target;
    if (!t || t.getAttribute("data-topo-seek") !== "range") return;
    _topoSeekInteracting = false;
  });
  grid.addEventListener("pointerup", function () {
    _topoSeekInteracting = false;
  });
  /* todo#97 — Force a repaint on window resize so the heatmap canvas
   * tracks the flexed track width. Bound once because this wiring is
   * idempotent-guarded by _topoSeekWired. */
  window.addEventListener("resize", function () {
    _topoSeekHeatRefresh(true);
  });
}

