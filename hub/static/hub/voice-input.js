/* Voice input module -- Web Speech API speech-to-text for chat input */
(function () {
  var SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition)
    return; /* browser does not support -- button stays hidden */

  var btn = document.getElementById("msg-voice");
  if (!btn) return;

  /* Show the button now that we know the API is available */
  btn.classList.remove("voice-btn-hidden");

  /* Language toggle: cycle between en-US and ja-JP */
  var VOICE_LANGS = [
    { code: "en-US", label: "EN" },
    { code: "ja-JP", label: "JA" },
  ];
  var langIdx = (navigator.language || "").startsWith("ja") ? 1 : 0;
  var langBtn = document.getElementById("msg-voice-lang");
  if (langBtn) {
    langBtn.classList.remove("voice-btn-hidden");
    langBtn.textContent = VOICE_LANGS[langIdx].label;
    langBtn.addEventListener("click", function () {
      langIdx = (langIdx + 1) % VOICE_LANGS.length;
      recognition.lang = VOICE_LANGS[langIdx].code;
      langBtn.textContent = VOICE_LANGS[langIdx].label;
    });
  }

  var recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = VOICE_LANGS[langIdx].code;

  var isListening = false;
  /* Snapshot of the textarea value when recording started, so interim
   * results can be replaced in-place without accumulating duplicates. */
  var baseText = "";

  btn.addEventListener("click", function () {
    if (isListening) {
      recognition.stop();
    } else {
      var input = document.getElementById("msg-input");
      baseText = input.value;
      recognition.start();
    }
  });

  recognition.addEventListener("start", function () {
    isListening = true;
    btn.classList.add("voice-active");
    btn.title = "Stop voice input";
  });

  recognition.addEventListener("end", function () {
    isListening = false;
    btn.classList.remove("voice-active");
    btn.title = "Voice input";
  });

  recognition.addEventListener("result", function (e) {
    var input = document.getElementById("msg-input");
    var transcript = "";
    for (var i = 0; i < e.results.length; i++) {
      transcript += e.results[i][0].transcript;
    }
    /* Append transcribed text after whatever was already in the textarea */
    var sep = baseText && !baseText.endsWith(" ") && transcript ? " " : "";
    input.value = baseText + sep + transcript;
    /* Trigger auto-resize */
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });

  recognition.addEventListener("error", function (e) {
    /* "no-speech" and "aborted" are normal -- user just stayed silent or
     * clicked stop before speaking. Other errors: log but don't crash. */
    if (e.error !== "no-speech" && e.error !== "aborted") {
      console.warn("Voice input error:", e.error);
    }
    isListening = false;
    btn.classList.remove("voice-active");
    btn.title = "Voice input";
  });

  /* Hands-free dictation: when chat.js sendMessage clears the textarea,
   * the next recognition.result event would otherwise re-render the
   * cumulative transcript on top of the now-empty input (because
   * recognition.continuous=true keeps the entire session in e.results
   * and baseText still points at pre-send text). Reset both baseText
   * AND the recognition session so the input stays clean and the user
   * can keep talking without manually clicking the mic between sends.
   * msg#6497 / msg#6500 — ywatanabe explicitly asks for this so the
   * mic can stay on continuously. */
  window.voiceInputResetAfterSend = function () {
    baseText = "";
    if (isListening) {
      try {
        recognition.stop();
      } catch (_) {}
      /* Restart on next tick — Web Speech API rejects start() while a
       * stop() is still in flight, so we wait for the "end" event
       * instead. Mark a flag so the end handler restarts. */
      _restartAfterStop = true;
    }
  };

  var _restartAfterStop = false;
  recognition.addEventListener("end", function () {
    if (_restartAfterStop) {
      _restartAfterStop = false;
      try {
        recognition.start();
      } catch (_) {}
    }
  });
})();
