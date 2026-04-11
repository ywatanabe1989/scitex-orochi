/* Bumped aggressively — every version change invalidates all old caches on
 * activate. The previous v5 served cache-first, which shadowed every JS/CSS
 * fix we shipped today. Do not drop below the highest previously-deployed
 * value or old clients will keep serving stale assets. */
const CACHE_NAME = "orochi-v201";
const SHELL_ASSETS = ["/"];

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

  // Network-first for JS/CSS/HTML under /static/ so fixes ship without
  // needing a cache version bump. The previous cache-first strategy caused
  // the fleet to keep serving stale scripts for hours after deploys.
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (response && response.ok) {
            const clone = response.clone();
            caches
              .open(CACHE_NAME)
              .then((cache) => cache.put(event.request, clone));
          }
          return response;
        })
        .catch(() => caches.match(event.request)),
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
