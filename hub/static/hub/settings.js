/* Token masking toggle for workspace settings */
function toggleToken(btn) {
  var code = btn.previousElementSibling;
  var full = code.dataset.token;
  if (code.classList.contains("token-masked")) {
    code.textContent = full;
    code.classList.remove("token-masked");
    btn.textContent = "\u{1F512}";
  } else {
    code.textContent = full.substring(0, 12) + "...";
    code.classList.add("token-masked");
    btn.textContent = "\u{1F441}";
  }
}

/* Copy token to clipboard */
function copyToken(btn) {
  /* The <code> is the first child of the <td> -- walk back from the copy button */
  var td = btn.parentElement;
  var code = td.querySelector("code[data-token]");
  if (!code) return;
  var full = code.dataset.token;
  var fallback = function () {
    var ta = document.createElement("textarea");
    ta.value = full;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
    } catch (e) {
      /* ignore */
    }
    document.body.removeChild(ta);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(full).catch(fallback);
  } else {
    fallback();
  }
  var orig = btn.textContent;
  btn.textContent = "\u2713";
  setTimeout(function () {
    btn.textContent = orig;
  }, 1200);
}

/* Render workspace icon preview on settings page */
(function () {
  var preview = document.getElementById("ws-icon-preview");
  if (!preview || typeof getWorkspaceIcon !== "function") return;
  var nameEl = document.querySelector(".workspace-name");
  var wsName = nameEl ? nameEl.textContent.trim() : "workspace";
  var wsIcon = window.__orochiWorkspaceIcon || "";
  preview.innerHTML = wsIcon
    ? '<span class="ws-emoji-icon ws-emoji-icon-lg">' + wsIcon + "</span>"
    : getWorkspaceIcon(wsName, 64);
})();
