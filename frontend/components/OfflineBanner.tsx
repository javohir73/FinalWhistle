"use client";

import { useEffect, useState } from "react";

/** Slim global banner while the device is offline, so live scores/standings are
 *  never mistaken for fresh data. Local bracket play keeps working offline. */
export function OfflineBanner() {
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    const sync = () => setOffline(!navigator.onLine);
    sync();
    window.addEventListener("online", sync);
    window.addEventListener("offline", sync);
    return () => {
      window.removeEventListener("online", sync);
      window.removeEventListener("offline", sync);
    };
  }, []);

  if (!offline) return null;
  return (
    <div
      role="status"
      className="border-b border-draw/30 bg-draw/15 px-4 py-1.5 text-center text-xs font-medium text-amber-ink"
    >
      You&apos;re offline — live scores and standings are paused. Your picks stay
      saved on this device.
    </div>
  );
}
