const CACHE_NAME = "orochi-v5";
const SHELL_ASSETS = [
  "/",
  "/static/hub/style.css",
  "/static/hub/components.css",
  "/static/hub/responsive.css",
  "/static/hub/config.js",
  "/static/hub/app.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS)),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)),
        ),
      ),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Network-first for API calls and WebSocket upgrades
  if (url.pathname.startsWith("/api") || url.pathname.startsWith("/ws")) {
    event.respondWith(fetch(event.request));
    return;
  }

  // Cache-first for static assets, network-first for HTML
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        const fetchPromise = fetch(event.request)
          .then((response) => {
            if (response.ok) {
              const clone = response.clone();
              caches
                .open(CACHE_NAME)
                .then((cache) => cache.put(event.request, clone));
            }
            return response;
          })
          .catch(() => cached);
        return cached || fetchPromise;
      }),
    );
    return;
  }

  // Network-first for everything else (index.html)
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches
            .open(CACHE_NAME)
            .then((cache) => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request)),
  );
});

/* ── Push notification handler ── */
self.addEventListener("push", (event) => {
  if (!event.data) return;

  let data;
  try {
    data = event.data.json();
  } catch (e) {
    data = { title: "Orochi", body: event.data.text() };
  }

  const title = data.title || "Orochi";
  const options = {
    body: data.body || "",
    icon: "/static/hub/orochi-icon.png",
    badge: "/static/hub/orochi-icon.png",
    tag: data.tag || "orochi-message",
    renotify: true,
    data: { url: data.url || "/" },
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

/* ── Notification click handler ── */
self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  const targetUrl =
    (event.notification.data && event.notification.data.url) || "/";

  event.waitUntil(
    clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((windowClients) => {
        // Focus existing dashboard tab if open
        for (const client of windowClients) {
          if (client.url.includes(self.location.origin) && "focus" in client) {
            return client.focus();
          }
        }
        // Otherwise open a new window
        return clients.openWindow(targetUrl);
      }),
  );
});
