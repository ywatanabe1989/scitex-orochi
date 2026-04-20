// @ts-nocheck
// Migrated classic-script file. Types intentionally loose during
// the big-bang JS-to-TS bundle migration. Narrow later, per-file.
/* Service Worker registration */
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(function (err) {
    console.error("SW registration failed:", err);
  });
}
