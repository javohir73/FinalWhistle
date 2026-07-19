"use client";

import { useEffect } from "react";
import { pingDailyActivity } from "@/lib/session";

/** Fires the once-a-day anonymous device ping (D7/D14 retention, see
 *  backend/app/api/retention.py) on mount. Renders nothing and never delays
 *  or blocks the page — mirrors ServiceWorker/SentryInit's shape, a
 *  side-effect-only component rather than a visible one like InstallAppPrompt. */
export function ActivityPing() {
  useEffect(() => {
    // pingDailyActivity() never rejects by contract (it swallows its own
    // failures), but a stray .catch here is cheap insurance against an
    // unhandled rejection if that contract ever slips.
    pingDailyActivity().catch(() => {});
  }, []);

  return null;
}
