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
  /* Restore the last-used language across sessions; ywatanabe asked for
   * this at msg#6528 ("最後に使った言語を記憶してほしい"). Falls back
   * to the browser locale on first use. */
  var LANG_KEY = "orochi-voice-lang";
  function _resolveInitialLangIdx() {
    try {
      var saved = localStorage.getItem(LANG_KEY);
      for (var i = 0; i < VOICE_LANGS.length; i++) {
        if (VOICE_LANGS[i].code === saved) return i;
      }
    } catch (_) {}
    return (navigator.language || "").startsWith("ja") ? 1 : 0;
  }
  var langIdx = _resolveInitialLangIdx();
  var langBtn = document.getElementById("msg-voice-lang");
  if (langBtn) {
    langBtn.classList.remove("voice-btn-hidden");
    langBtn.textContent = VOICE_LANGS[langIdx].label;
    langBtn.addEventListener("click", function () {
      _cycleLang();
      /* Hand focus back to the textarea so Enter still sends. */
      try { document.getElementById("msg-input").focus(); } catch (_) {}
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

  function _toggleVoice() {
    var input = document.getElementById("msg-input");
    if (isListening) {
      recognition.stop();
    } else {
      baseText = input ? input.value : "";
      try {
        recognition.start();
      } catch (_) {}
    }
    /* Always hand focus back to the textarea so the next Enter goes to
     * sendMessage and not to a re-click of the mic button. msg#6537 —
     * ywatanabe pressed Enter expecting send, hit the mic button instead
     * (it had focus from the previous click). */
    if (input) {
      try { input.focus(); } catch (_) {}
    }
  }
  function _cycleLang() {
    langIdx = (langIdx + 1) % VOICE_LANGS.length;
    recognition.lang = VOICE_LANGS[langIdx].code;
    if (langBtn) langBtn.textContent = VOICE_LANGS[langIdx].label;
    btn.title =
      (isListening ? "Stop voice input" : "Voice input") +
      " · " + VOICE_LANGS[langIdx].label +
      " · right-click to change language · Ctrl+M to toggle";
    /* Persist for next session (msg#6528). */
    try { localStorage.setItem(LANG_KEY, VOICE_LANGS[langIdx].code); } catch (_) {}
  }
  /* todo#332 v2: expose toggle so chat.js Alt+Enter can trigger it */
  window.toggleVoiceInput = _toggleVoice;
  btn.addEventListener("click", _toggleVoice);
  /* Right-click on the mic button cycles language without leaving the
   * keyboard shortcut path or needing the separate EN/JA pill button.
   * msg#6515 — ywatanabe wants language switch on right-click. */
  btn.addEventListener("contextmenu", function (e) {
    e.preventDefault();
    _cycleLang();
  });
  /* Keyboard shortcut: Ctrl+M (or Cmd+M) toggles voice input from
   * anywhere on the page. msg#6516 — ywatanabe wants no-mouse access.
   * Cmd+M is reserved by macOS Safari (minimize), so we accept the
   * Ctrl variant on every platform and the Alt+V backup on macOS. */
  document.addEventListener("keydown", function (e) {
    if (
      (e.ctrlKey && (e.key === "m" || e.key === "M")) ||
      (e.altKey && (e.key === "v" || e.key === "V"))
    ) {
      e.preventDefault();
      _toggleVoice();
    }
  });
  /* Initial title with the new shortcut hint. */
  btn.title =
    "Voice input · " + VOICE_LANGS[langIdx].label +
    " · right-click to change language · Ctrl+M to toggle";

  recognition.addEventListener("start", function () {
    isListening = true;
    btn.classList.add("voice-active");
    btn.title = "Stop voice input";
    /* todo#339/#340: pulse the input border red while recording */
    var __input = document.getElementById("msg-input");
    if (__input) __input.classList.add("voice-recording");
  });

  recognition.addEventListener("end", function () {
    isListening = false;
    btn.classList.remove("voice-active");
    btn.title = "Voice input";
    var __input = document.getElementById("msg-input");
    if (__input) __input.classList.remove("voice-recording");
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
