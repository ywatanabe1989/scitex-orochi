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
  /* Restore the last-used language across sessions. Falls back
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
      try { document.getElementById("msg-input").focus(); } catch (_) {}
    });
  }

  var recognition = null;
  var isListening = false;
  var _userStopped = false;
  var baseText = "";
  var _restartAfterStop = false;
  var _suppressResults = false;
  var _voiceTarget = null; /* textarea receiving voice transcription */
  /* Generation counter: every new recognition instance gets a generation
   * number. End/error handlers check their captured generation against the
   * current one and no-op if they're stale. This prevents the race condition
   * where aborting an old instance fires a late `end` event that corrupts
   * the new instance's state (msg#10664/10667 root cause). */
  var _generation = 0;

  function _setStoppedUI() {
    isListening = false;
    btn.classList.remove("voice-active");
    btn.title = "Voice input · " + VOICE_LANGS[langIdx].label +
      " · right-click to change language · Alt+Enter / Ctrl+Enter / Ctrl+M to toggle";
    var input = document.getElementById("msg-input");
    if (input) input.classList.remove("voice-recording");
  }

  function _createRecognition() {
    var myGen = ++_generation; /* capture generation at creation time */
    var r = new SpeechRecognition();
    r.continuous = true;
    r.interimResults = true;
    r.lang = VOICE_LANGS[langIdx].code;

    r.addEventListener("start", function () {
      if (myGen !== _generation) return; /* stale instance */
      isListening = true;
      _userStopped = false;
      btn.classList.add("voice-active");
      btn.title = "Stop voice input";
      var input = document.getElementById("msg-input");
      if (input) input.classList.add("voice-recording");
    });

    r.addEventListener("end", function () {
      if (myGen !== _generation) return; /* stale instance — discard */
      if (_restartAfterStop) {
        _restartAfterStop = false;
        _suppressResults = false;
        recognition = _createRecognition();
        try { recognition.start(); } catch (_) {}
        return;
      }
      if (isListening && !_userStopped) {
        /* Unexpected end — recreate instance to recover */
        isListening = false;
        setTimeout(function () {
          if (myGen !== _generation) return; /* superseded by a newer toggle */
          if (!_userStopped) {
            recognition = _createRecognition();
            try { recognition.start(); } catch (_) {
              _setStoppedUI();
            }
          }
        }, 150);
        return;
      }
      _setStoppedUI();
    });

    r.addEventListener("result", function (e) {
      if (myGen !== _generation) return;
      if (_suppressResults) return;
      /* Write to whichever textarea is active — main or thread reply */
      var input = _voiceTarget || document.getElementById("msg-input");
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
      if (myGen !== _generation) return;
      if (e.error !== "no-speech" && e.error !== "aborted") {
        console.warn("Voice input error:", e.error);
      }
      _setStoppedUI();
    });

    return r;
  }

  function _toggleVoice() {
    /* Determine target textarea: thread reply textarea if focused, else main */
    var focused = document.activeElement;
    var threadTextarea = focused && focused.closest && focused.closest(".thread-panel") ? focused : null;
    var input = (threadTextarea && threadTextarea.tagName === "TEXTAREA") ? threadTextarea : document.getElementById("msg-input");

    if (isListening) {
      _userStopped = true;
      /* Bump generation first so any pending end events from this instance
       * are treated as stale. Then stop (which will fire end, but it will
       * see myGen !== _generation and no-op after our generation bump). */
      _generation++;
      _setStoppedUI();
      if (recognition) {
        try { recognition.abort(); } catch (_) {}
      }
      recognition = null;
      _voiceTarget = null;
    } else {
      /* Discard old instance (abort is safe even on already-ended instances) */
      if (recognition) {
        try { recognition.abort(); } catch (_) {}
        recognition = null;
      }
      _voiceTarget = input;
      recognition = _createRecognition();
      _userStopped = false;
      baseText = input ? input.value : "";
      try {
        recognition.start();
      } catch (_) {
        /* start() failed synchronously — reset UI */
        _generation++;
        _setStoppedUI();
      }
    }
    /* Always hand focus back to the textarea. */
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
    try { localStorage.setItem(LANG_KEY, VOICE_LANGS[langIdx].code); } catch (_) {}
  }

  window.toggleVoiceInput = _toggleVoice;
  /* Expose lang cycle so thread panel can add its own EN/JA button */
  window.cycleVoiceLang = _cycleLang;
  btn.addEventListener("click", _toggleVoice);
  btn.addEventListener("contextmenu", function (e) {
    e.preventDefault();
    _cycleLang();
  });

  document.addEventListener("keydown", function (e) {
    /* Escape always stops voice — emergency exit regardless of focus/thread state */
    if (e.key === "Escape" && isListening) {
      /* Don't preventDefault — let other Escape handlers (modal close etc.) also fire */
      _toggleVoice();
      return;
    }
    if (
      (e.ctrlKey && (e.key === "m" || e.key === "M")) ||
      (e.altKey && (e.key === "v" || e.key === "V"))
    ) {
      e.preventDefault();
      _toggleVoice();
      return;
    }
    if (e.key === "Enter" && (e.ctrlKey || e.altKey)) {
      /* Toggle voice — works in both main textarea and thread panel */
      if (typeof activeTab !== "undefined" && activeTab === "chat") {
        e.preventDefault();
        _toggleVoice();
      }
    }
  }, true);

  btn.title =
    "Voice input · " + VOICE_LANGS[langIdx].label +
    " · right-click to change language · Alt+Enter / Ctrl+Enter / Ctrl+M to toggle";

  window.voiceInputResetAfterSend = function () {
    baseText = "";
    _suppressResults = true;
    if (isListening) {
      _restartAfterStop = true;
      /* Bump generation so the current instance's end fires but is treated
       * as the restart-trigger rather than a stale stop. The _restartAfterStop
       * path in the end handler checks this correctly. */
      if (recognition) {
        try { recognition.stop(); } catch (_) {}
      }
    }
  };
})();
