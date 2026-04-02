/* Service Worker registration -- loaded from index.html */
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(function (err) {
    console.error("SW registration failed:", err);
  });
}
