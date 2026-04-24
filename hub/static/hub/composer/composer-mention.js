/* composer/composer-mention.js — mirror of composer-mention.ts. Thin
 * adapter around the global mention.js autocomplete for classic-script
 * consumers. */
/* globals: initMentionAutocomplete, mentionDropdown, mentionSelectedIndex */

(function () {
  function wireComposerMention(input) {
    if (!input) return;
    if (typeof initMentionAutocomplete === "function") {
      initMentionAutocomplete(input);
    }
  }

  function isMentionDropdownOpen() {
    return !!(
      typeof mentionDropdown !== "undefined" &&
      mentionDropdown &&
      mentionDropdown.classList &&
      mentionDropdown.classList.contains("visible") &&
      typeof mentionSelectedIndex !== "undefined" &&
      mentionSelectedIndex >= 0
    );
  }

  window.wireComposerMention = wireComposerMention;
  window.isMentionDropdownOpen = isMentionDropdownOpen;
})();
