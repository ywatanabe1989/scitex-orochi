// @ts-nocheck
/* Service Worker registration */
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(function (err) {
    console.error("SW registration failed:", err);
  });
}
