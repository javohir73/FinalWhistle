"use client";

import { useEffect } from "react";

/** Registers the service worker (production only) so the app is installable and
 *  works offline. No-op in dev to avoid stale-cache headaches during HMR.
 *
 *  Updates: sw.js itself carries the cache version; the browser revalidates it
 *  on navigation, and we additionally check when the app returns to the
 *  foreground — important for installed/standalone sessions that stay open for
 *  days. The worker uses skipWaiting + clients.claim, and pages are
 *  network-first, so a new version takes over cleanly without a forced reload. */
export function ServiceWorker() {
  useEffect(() => {
    if (
      typeof window === "undefined" ||
      !("serviceWorker" in navigator) ||
      process.env.NODE_ENV !== "production"
    ) {
      return;
    }

    let registration: ServiceWorkerRegistration | undefined;

    const register = () => {
      navigator.serviceWorker
        .register("/sw.js")
        .then((reg) => {
          registration = reg;
        })
        .catch(() => {});
    };

    // Register after the page has loaded so the SW doesn't compete with the
    // initial resource fetches.
    if (document.readyState === "complete") register();
    else window.addEventListener("load", register, { once: true });

    const onVisible = () => {
      if (document.visibilityState === "visible") {
        registration?.update().catch(() => {});
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("load", register);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);
  return null;
}
