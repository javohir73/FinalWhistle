"use client";

import { useEffect } from "react";

/** Initializes Sentry browser error tracking — only when NEXT_PUBLIC_SENTRY_DSN
 *  is configured (safe no-op otherwise). Loaded lazily so the SDK stays out of
 *  the main bundle until it's actually used. Captures client runtime errors;
 *  backend errors are tracked separately via the FastAPI Sentry integration. */
export function SentryInit() {
  useEffect(() => {
    const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
    if (!dsn || typeof window === "undefined") return;
    const w = window as unknown as { __sentryInited?: boolean };
    if (w.__sentryInited) return;
    w.__sentryInited = true;
    import("@sentry/nextjs")
      .then((Sentry) => {
        Sentry.init({
          dsn,
          environment: process.env.NEXT_PUBLIC_ENV ?? "production",
          tracesSampleRate: 0, // errors only
        });
        Sentry.setTag("model_version", process.env.NEXT_PUBLIC_MODEL_VERSION ?? "poisson-elo-v0.1");
      })
      .catch(() => {
        /* never let monitoring break the app */
      });
  }, []);
  return null;
}
