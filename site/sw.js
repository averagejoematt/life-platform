/*
  sw.js — The Measured Life PWA service worker (the installable Cockpit app).
  Strategy:
    - Navigations + /api/*  → network-first (data must stay fresh), fall back to
      cache, then to the cached Cockpit shell when fully offline.
    - Hashed/static assets  → cache-first (filenames are content-hashed → immutable),
      with background revalidate.
    - Audio (/panelcast,/podcast *.wav|*.mp3) → pass through (never cache big media).
  Same-origin only. Bump VERSION to roll the cache. Served with a short TTL so the
  browser always re-checks (see deploy/sync_site_to_s3.sh).
*/
const VERSION = "v1";
const SHELL = `tml-shell-${VERSION}`;
const RUNTIME = `tml-runtime-${VERSION}`;
const SHELL_URLS = ["/now/", "/", "/manifest.webmanifest", "/assets/icons/icon-192.png", "/assets/icons/icon-512.png", "/favicon.ico"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches
      .open(SHELL)
      .then((c) => c.addAll(SHELL_URLS).catch(() => {}))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => !k.endsWith(VERSION)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return; // leave cross-origin (audio CDNs, etc.) alone
  if (/\.(wav|mp3|m4a)$/i.test(url.pathname)) return; // never cache large media

  // Fresh-first for live data + page navigations.
  if (url.pathname.startsWith("/api/") || req.mode === "navigate") {
    e.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(RUNTIME).then((c) => c.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(req).then((r) => r || caches.match("/now/"))),
    );
    return;
  }

  // Cache-first for immutable hashed assets.
  e.respondWith(
    caches.match(req).then(
      (cached) =>
        cached ||
        fetch(req).then((res) => {
          const copy = res.clone();
          caches.open(RUNTIME).then((c) => c.put(req, copy)).catch(() => {});
          return res;
        }),
    ),
  );
});
