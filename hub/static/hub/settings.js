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

/* Render workspace icon preview on settings page */
(function () {
  var preview = document.getElementById("ws-icon-preview");
  if (!preview || typeof getWorkspaceIcon !== "function") return;
  var nameEl = document.querySelector(".workspace-name");
  var wsName = nameEl ? nameEl.textContent.trim() : "workspace";
  preview.innerHTML = getWorkspaceIcon(wsName, 64);
})();
