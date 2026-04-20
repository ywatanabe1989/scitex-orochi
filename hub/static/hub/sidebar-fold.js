/* Orochi Dashboard -- sidebar fold toggle
 *
 * Desktop affordance to collapse the left sidebar and reclaim its
 * ~280px for the main content area. Parallel to the mobile hamburger
 * (#sidebar-toggle); this one is always visible on desktop and hidden
 * at narrow viewports via sidebar-fold.css.
 *
 * Chevron: '‹' (open — click to fold), '›' (folded — click to unfold).
 * State persists in localStorage["orochi.sidebarFolded"] ("1" | "0").
 * Keyboard shortcut: Ctrl+B / Cmd+B (ignored while typing in inputs).
 */
(function () {
  var LS_KEY = "orochi.sidebarFolded";
  var container = document.querySelector(".container");
  var btn = document.getElementById("sidebar-fold");
  if (!container || !btn) return;

  function applyState(folded) {
    container.classList.toggle("sidebar-folded", !!folded);
    btn.innerHTML = folded ? "\u203A" : "\u2039";
    btn.title = folded
      ? "Expand sidebar (Ctrl+B)"
      : "Collapse sidebar (Ctrl+B)";
    btn.setAttribute(
      "aria-label",
      folded ? "Expand sidebar" : "Collapse sidebar",
    );
  }

  var initial = false;
  try {
    initial = localStorage.getItem(LS_KEY) === "1";
  } catch (_e) {
    /* localStorage unavailable (private mode / disabled) -- default open. */
  }
  applyState(initial);

  btn.addEventListener("click", function () {
    var folded = !container.classList.contains("sidebar-folded");
    applyState(folded);
    try {
      localStorage.setItem(LS_KEY, folded ? "1" : "0");
    } catch (_e) {
      /* Ignore quota / disabled storage; in-memory state still toggles. */
    }
  });

  /* Ctrl+B / Cmd+B -- keyboard shortcut. Ignore while the user is
   * typing in an input / textarea / contenteditable so we don't eat
   * the browser's bold shortcut in message composition. */
  document.addEventListener("keydown", function (ev) {
    if (!(ev.ctrlKey || ev.metaKey)) return;
    if (ev.key !== "b" && ev.key !== "B") return;
    var t = ev.target;
    var isInput =
      t &&
      (t.tagName === "INPUT" ||
        t.tagName === "TEXTAREA" ||
        t.isContentEditable);
    if (isInput) return;
    ev.preventDefault();
    btn.click();
  });
})();
