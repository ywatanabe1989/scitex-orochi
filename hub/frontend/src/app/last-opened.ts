// @ts-nocheck
/* Last-opened UI state persistence across hard reload (msg#16999).
 *
 * Persists `{activeTab, activeChannel}` to localStorage on every
 * selection change so Ctrl+Shift+R lands the user back on the tab +
 * channel they were viewing. Value shape is versioned via the key
 * suffix (`.v1`) so a future schema change can bump to `.v2` without
 * a migration — callers just read whatever is current and fall back
 * silently on shape mismatch.
 *
 * Legacy keys (`orochi_active_tab`, `orochi_active_channel`) are
 * written in parallel so older bundles and in-flight tabs keep
 * working during a staged deploy; once the new bundle is universal
 * those can be removed.
 *
 * scrollPosition is intentionally NOT included in v1 — the chat feed
 * aggressively snaps to bottom on channel activation (tabs.ts line
 * 163), and the Overview / TODO / other tabs have their own
 * view-specific scroll anchors. Adding a global scroll field would
 * cost more correctness debt than it buys.
 */

const LAST_OPENED_KEY = "orochi.ui.lastOpened.v1";
const LEGACY_TAB_KEY = "orochi_active_tab";
const LEGACY_CHANNEL_KEY = "orochi_active_channel";

type LastOpened = {
  activeTab?: string | null;
  activeChannel?: string | null;
};

/* Read the persisted record. Returns {} on storage error / parse
 * failure / schema mismatch — callers treat a missing field as
 * "use default" and never crash on the hydrate path. */
export function readLastOpened(): LastOpened {
  try {
    const raw = localStorage.getItem(LAST_OPENED_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object") {
        return {
          activeTab:
            typeof parsed.activeTab === "string" ? parsed.activeTab : null,
          activeChannel:
            typeof parsed.activeChannel === "string"
              ? parsed.activeChannel
              : null,
        };
      }
    }
  } catch (_) {
    /* Parse error or storage disabled — fall through to legacy. */
  }
  /* Back-compat: earlier bundles wrote two flat keys. Fold them into
   * the v1 shape so users upgrading a tab mid-session don't lose their
   * spot. */
  try {
    const legacyTab = localStorage.getItem(LEGACY_TAB_KEY);
    const legacyCh = localStorage.getItem(LEGACY_CHANNEL_KEY);
    if (legacyTab || legacyCh) {
      return {
        activeTab: legacyTab || null,
        activeChannel:
          legacyCh && legacyCh !== "__all__" ? legacyCh : null,
      };
    }
  } catch (_) {}
  return {};
}

/* Merge-write a partial update. Only the provided fields are
 * overwritten — omit `activeChannel` to update only the tab, etc.
 * Any localStorage error (private mode, SecurityError, quota) is
 * swallowed; persistence is a nice-to-have, never a hard dependency. */
export function writeLastOpened(patch: LastOpened): void {
  try {
    const current = readLastOpened();
    const next: LastOpened = {
      activeTab:
        "activeTab" in patch ? patch.activeTab : current.activeTab || null,
      activeChannel:
        "activeChannel" in patch
          ? patch.activeChannel
          : current.activeChannel || null,
    };
    localStorage.setItem(LAST_OPENED_KEY, JSON.stringify(next));
    /* Mirror to legacy keys so older-bundle tabs in the same browser
     * stay in sync. Safe to delete once the bundle rollout is complete. */
    if ("activeTab" in patch && patch.activeTab) {
      localStorage.setItem(LEGACY_TAB_KEY, patch.activeTab);
    }
    if ("activeChannel" in patch) {
      localStorage.setItem(
        LEGACY_CHANNEL_KEY,
        patch.activeChannel == null ? "__all__" : patch.activeChannel,
      );
    }
  } catch (_) {
    /* storage disabled / SecurityError — accept the loss. */
  }
}

/* Clear the persisted channel after a missing-channel fallback so the
 * next reload doesn't re-trigger the same miss. Preserves the tab. */
export function clearLastOpenedChannel(): void {
  writeLastOpened({ activeChannel: null });
}
