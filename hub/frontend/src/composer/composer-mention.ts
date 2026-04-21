// @ts-nocheck
/* composer/composer-mention.ts — adapter that wires the existing
 * mention.ts autocomplete (cachedAgentNames + SPECIAL_MENTIONS + the
 * single shared #mention-dropdown) to any textarea belonging to a
 * composer surface.
 *
 * Why a thin wrapper: mention.ts already does the lookup, rendering,
 * and keyboard navigation. Threads and the group-compose modal used
 * to call `initMentionAutocomplete` directly (threads/panel.ts does
 * today); the graph-compose popup didn't call it at all (feature gap
 * #311). The composer SSoT hides that inconsistency behind a single
 * `wireComposerMention(input)` call site.
 *
 * `isMentionDropdownOpen()` is exposed so the composer's keydown /
 * submit logic can defer to the dropdown when it's the active
 * target (plain Enter = pick mention, not send). Mirrors the check
 * Chat + Reply composers already performed inline. */

import {
  handleMentionKeydown,
  initMentionAutocomplete,
  mentionDropdown,
  mentionSelectedIndex,
} from "../mention";

export function wireComposerMention(input: HTMLElement): void {
  if (!input) return;
  if (typeof initMentionAutocomplete === "function") {
    initMentionAutocomplete(input);
  }
}

export function isMentionDropdownOpen(): boolean {
  return !!(
    mentionDropdown &&
    mentionDropdown.classList &&
    mentionDropdown.classList.contains("visible") &&
    mentionSelectedIndex >= 0
  );
}

/* Re-export for call sites that previously imported from mention.ts
 * directly; keeps the composer module self-contained. */
export { handleMentionKeydown, mentionDropdown, mentionSelectedIndex };
