const CACHE_NAME = "cinematokyo-v4";
const CORE_ASSETS = [
  "./",
  "./manifest.webmanifest",
  "./icons/icon-192.png",
  "./icons/icon-512.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(CORE_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.map((key) => (key === CACHE_NAME ? null : caches.delete(key)))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") {
    return;
  }

  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) {
    return;
  }

  const isHtml =
    url.pathname.endsWith("/");
  const isShowtimeData =
    url.pathname.startsWith("/data/") && url.pathname.endsWith(".json");
  if (isHtml || isShowtimeData) {
    event.respondWith(
      fetch(event.request)
        .then((response) =>
          response.ok
            ? caches
                .open(CACHE_NAME)
                .then((cache) => cache.put(event.request, response.clone()))
                .catch(() => null)
                .then(() => response)
            : Promise.reject(response)
        )
        .catch(() => caches.match(event.request))
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cached) =>
      cached ||
      fetch(event.request).then((response) => {
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        return response;
      })
    )
  );
});
