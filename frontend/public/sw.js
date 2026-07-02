/* FinalWhistle service worker — installability + safe offline support.
 *
 * Caching contract (fw-v3 — bumped so activate evicts the cached /my-bracket
 * page, which now redirects to /brackets):
 *   - /backend-api/* is NEVER touched. The backend proxy is SAME-origin (a
 *     Next.js rewrite), so an origin check is not enough — auth, live scores,
 *     brackets and leaderboard data must always hit the network.
 *   - Page navigations are network-first; offline falls back to the last
 *     cached copy of that page, else the offline fallback page.
 *   - Cache-first ONLY for immutable/static assets (hashed /_next/static,
 *     icons, images, fonts). Everything else (RSC payloads, manifest,
 *     analytics) passes through untouched.
 *   - Only res.ok responses are ever cached, so a 401/404/500 can never be
 *     replayed from cache (the fw-v1 worker cached a 401 /auth/me, which made
 *     signed-in users appear logged out after refresh).
 *   - Bumping CACHE invalidates everything: activate deletes old caches and
 *     claims clients, so stale installs upgrade cleanly on next load.
 */
const CACHE = "fw-v3";
const OFFLINE_URL = "/offline.html";
const PRECACHE = [OFFLINE_URL, "/icon-192.png"];

const STATIC_ASSET = /\.(?:png|jpg|jpeg|gif|svg|ico|webp|avif|woff2?|ttf)$/;

function isStaticAsset(pathname) {
  return pathname.startsWith("/_next/static/") || STATIC_ASSET.test(pathname);
}

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
      )
      .then(() => self.clients.claim())
  );
});

async function networkFirstPage(event, req) {
  const cache = await caches.open(CACHE);
  try {
    const res = await fetch(req);
    if (res.ok) {
      const copy = res.clone();
      event.waitUntil(cache.put(req, copy));
    }
    return res;
  } catch {
    const cached = await cache.match(req);
    return cached || (await cache.match(OFFLINE_URL)) || Response.error();
  }
}

async function cacheFirstAsset(event, req) {
  const cached = await caches.match(req);
  if (cached) return cached;
  const res = await fetch(req);
  if (res.ok) {
    const copy = res.clone();
    event.waitUntil(caches.open(CACHE).then((c) => c.put(req, copy)));
  }
  return res;
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // flags CDN, Sentry, etc.

  // The same-origin backend proxy: auth, live scores, brackets, leaderboard.
  // Never intercept — these must always be fresh from the network.
  if (url.pathname.startsWith("/backend-api/")) return;

  if (req.mode === "navigate") {
    event.respondWith(networkFirstPage(event, req));
    return;
  }

  if (isStaticAsset(url.pathname)) {
    event.respondWith(cacheFirstAsset(event, req));
  }
  // Anything else (RSC ?_rsc= payloads, manifest, analytics beacons) is left
  // to the network — caching those froze page data in fw-v1.
});
