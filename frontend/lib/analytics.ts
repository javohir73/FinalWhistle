/** Thin, fail-safe wrapper around Vercel Web Analytics custom events.
 *
 *  Uses a dynamic import so the analytics module is only pulled in when an event
 *  actually fires (not at render time) — this keeps it out of SSR and the jest
 *  environment, and a failed load never breaks the interaction. Page views are
 *  tracked automatically by <Analytics/> in the root layout; this is only for
 *  the custom interaction events. */
export type AnalyticsProps = Record<string, string | number | boolean | null>;

export function trackEvent(name: string, props?: AnalyticsProps): void {
  if (typeof window === "undefined") return;
  import("@vercel/analytics")
    .then(({ track }) => track(name, props))
    .catch(() => {
      /* analytics is best-effort; never surface errors to the user */
    });
}
