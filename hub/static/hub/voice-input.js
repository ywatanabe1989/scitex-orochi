/* Voice input module -- Web Speech API speech-to-text for chat input */
(function () {
  var SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition)
    return; /* browser does not support -- button stays hidden */

  /* On iOS/iPadOS, hide custom mic buttons and let the native keyboard mic
   * handle voice input. The native mic is more reliable and familiar on iOS. */
  var isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  if (isIOS) return;

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

  var recognition = null; /* created fresh on each start to prevent stale state */
  var isListening = false;
  var _userStopped = false; /* true when the user explicitly clicked stop */
  /* Snapshot of the textarea value when recording started, so interim
   * results can be replaced in-place without accumulating duplicates. */
  var baseText = "";
  var _restartAfterStop = false;
  var _suppressResults = false;

  function _createRecognition() {
    var r = new SpeechRecognition();
    r.continuous = true;
    r.interimResults = true;
    r.lang = VOICE_LANGS[langIdx].code;

    r.addEventListener("start", function () {
      isListening = true;
      _userStopped = false;
      btn.classList.add("voice-active");
      btn.title = "Stop voice input";
      var input = document.getElementById("msg-input");
      if (input) input.classList.add("voice-recording");
    });

    r.addEventListener("end", function () {
      if (_restartAfterStop) {
        _restartAfterStop = false;
        _suppressResults = false;
        recognition = _createRecognition();
        try { recognition.start(); } catch (_) {}
        return;
      }
      if (isListening && !_userStopped) {
        /* Unexpected end — recreate instance to recover from stale state */
        isListening = false; /* reset flag before restart attempt */
        setTimeout(function () {
          if (!_userStopped) {
            recognition = _createRecognition();
            try { recognition.start(); } catch (_) {
              /* restart failed — update UI to reflect stopped state */
              btn.classList.remove("voice-active");
              btn.title = "Voice input · " + VOICE_LANGS[langIdx].label +
                " · right-click to change language · Alt+Enter / Ctrl+Enter / Ctrl+M to toggle";
              var input = document.getElementById("msg-input");
              if (input) input.classList.remove("voice-recording");
            }
          }
        }, 150);
        return;
      }
      /* Normal stop: update UI */
      isListening = false;
      btn.classList.remove("voice-active");
      btn.title = "Voice input · " + VOICE_LANGS[langIdx].label +
        " · right-click to change language · Alt+Enter / Ctrl+Enter / Ctrl+M to toggle";
      var input = document.getElementById("msg-input");
      if (input) input.classList.remove("voice-recording");
    });

    r.addEventListener("result", function (e) {
      if (_suppressResults) return;
      var input = document.getElementById("msg-input");
      var transcript = "";
      for (var i = 0; i < e.results.length; i++) {
        transcript += e.results[i][0].transcript;
      }
      var sep = baseText && !baseText.endsWith(" ") && transcript ? " " : "";
      if (input) {
        input.value = baseText + sep + transcript;
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });

    r.addEventListener("error", function (e) {
      if (e.error !== "no-speech" && e.error !== "aborted") {
        console.warn("Voice input error:", e.error);
      }
      isListening = false;
      btn.classList.remove("voice-active");
      btn.title = "Voice input · " + VOICE_LANGS[langIdx].label +
        " · right-click to change language · Alt+Enter / Ctrl+Enter / Ctrl+M to toggle";
      var input = document.getElementById("msg-input");
      if (input) input.classList.remove("voice-recording");
    });

    return r;
  }

  function _toggleVoice() {
    var input = document.getElementById("msg-input");
    if (isListening) {
      _userStopped = true;
      try { recognition.stop(); } catch (_) {
        /* If stop() throws, forcibly reset state */
        isListening = false;
        btn.classList.remove("voice-active");
        if (input) input.classList.remove("voice-recording");
      }
    } else {
      /* Abort any stale instance and start fresh */
      if (recognition) {
        try { recognition.abort(); } catch (_) {}
      }
      recognition = _createRecognition();
      _userStopped = false;
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
    if (recognition) recognition.lang = VOICE_LANGS[langIdx].code;
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
  /* Use capture phase so this fires before bubble-phase handlers on textareas */
  document.addEventListener("keydown", function (e) {
    /* Ctrl+M / Cmd+M or Alt+V toggles voice from anywhere */
    if (
      (e.ctrlKey && (e.key === "m" || e.key === "M")) ||
      (e.altKey && (e.key === "v" || e.key === "V"))
    ) {
      e.preventDefault();
      _toggleVoice();
      return;
    }
    /* Ctrl+Enter or Alt+Enter toggles voice when Chat tab is active (msg#9375 / msg#9926).
     * Skip if focus is inside the thread panel — thread has its own Alt+Enter handler. */
    if (e.key === "Enter" && (e.ctrlKey || e.altKey)) {
      var focused = document.activeElement;
      var inThread = focused && focused.closest && focused.closest(".thread-panel");
      if (!inThread && typeof activeTab !== "undefined" && activeTab === "chat") {
        e.preventDefault();
        _toggleVoice();
      }
    }
  }, true /* capture phase — fires reliably before textarea keydown handlers */);
  /* Initial title with the new shortcut hint. */
  btn.title =
    "Voice input · " + VOICE_LANGS[langIdx].label +
    " · right-click to change language · Alt+Enter / Ctrl+Enter / Ctrl+M to toggle";

  /* Hands-free dictation: reset baseText + restart recognition after send.
   * msg#6497/6500 — ywatanabe wants continuous dictation across sends. */
  window.voiceInputResetAfterSend = function () {
    baseText = "";
    _suppressResults = true;
    if (isListening) {
      _restartAfterStop = true;
      try { recognition.stop(); } catch (_) {}
    }
  };
})();
