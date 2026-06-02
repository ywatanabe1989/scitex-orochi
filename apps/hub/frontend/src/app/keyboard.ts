// @ts-nocheck
import { closeEmojiPicker } from "../emoji-picker";
import { closeThreadPanel } from "../threads/panel";


/* Global ESC handler — close any visible popups/modals (#207) */
document.addEventListener("keydown", function (e) {
  if (e.key !== "Escape") return;
  if (typeof closeEmojiPicker === "function") {
    var emojiOverlay = document.querySelector(".emoji-picker-overlay.visible");
    if (emojiOverlay) {
      closeEmojiPicker();
      e.preventDefault();
      return;
    }
  }
  if (typeof closeThreadPanel === "function") {
    var threadPanel = document.querySelector(".thread-panel.open");
    if (threadPanel) {
      closeThreadPanel();
      e.preventDefault();
      return;
    }
  }
  if (typeof closeSketchPanel === "function") {
    var sketchPanel = document.querySelector(".sketch-panel.open");
    if (sketchPanel) {
      closeSketchPanel();
      e.preventDefault();
      return;
    }
  }
  var generic = document.querySelector(
    ".emoji-picker-overlay.visible, .modal.open, .popup.visible, .long-press-menu",
  );
  if (generic) {
    generic.classList.remove("visible", "open");
    if (generic.classList.contains("long-press-menu")) generic.remove();
    e.preventDefault();
    return;
  }
  /* Inline-style-based modals (display:flex toggled via style) —
   * channel-topic-modal, channel-export-modal, channel-members-panel,
   * and any future role="dialog" element that uses this pattern.
   * Close the top-most visible one. */
  var styleModals = document.querySelectorAll(
    '[role="dialog"], .ch-topic-modal, .ch-export-modal, .ch-members-panel, ' +
      "#channel-topic-modal, #channel-export-modal, #channel-members-panel, " +
      "#new-dm-modal, .dm-modal",
  );
  for (var i = 0; i < styleModals.length; i++) {
    var m = styleModals[i];
    var isVisible =
      m.hidden !== true &&
      getComputedStyle(m).display !== "none" &&
      getComputedStyle(m).visibility !== "hidden";
    if (!isVisible) continue;
    m.style.display = "none";
    m.hidden = true;
    e.preventDefault();
    return;
  }
});
