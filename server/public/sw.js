// Service worker for the installed PWA.
//
// Scope is narrow on purpose: cache the shell so the app opens offline,
// and never touch /api. The document itself already lives in localStorage,
// so a cached API response would only ever be a worse, staler copy of
// something the page already has — and a cached POST is nonsense.
//
// Bump CACHE when the shell changes; the activate handler drops old ones.

const CACHE = "list-shell-v1";
const SHELL = [
  "/",
  "/index.html",
  "/manifest.webmanifest",
  "/icon-192.png",
  "/icon-512.png",
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE)
      // addAll rejects the whole batch if any single request fails, which
      // would leave the worker uninstalled. Tolerate a missing icon.
      .then(cache => Promise.allSettled(SHELL.map(url => cache.add(url))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== CACHE).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", event => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;

  // Network-first for the shell so a redeploy is picked up on the next
  // online launch, falling back to cache when offline. Cache-first would
  // pin the app to whatever version it installed with.
  event.respondWith(
    fetch(request)
      .then(response => {
        if (response && response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then(cache => cache.put(request, copy));
        }
        return response;
      })
      .catch(() => caches.match(request).then(hit => hit || caches.match("/index.html")))
  );
});
