"use client";

import { useEffect } from "react";

/** Registers the service worker (production only) so the app is installable and
 *  works offline. No-op in dev to avoid stale-cache headaches during HMR. */
export function ServiceWorker() {
  useEffect(() => {
    if (
      typeof window !== "undefined" &&
      "serviceWorker" in navigator &&
      process.env.NODE_ENV === "production"
    ) {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    }
  }, []);
  return null;
}
