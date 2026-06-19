"use client";

import { useTimezone } from "@/lib/useTimezone";
import { dayHeading, kickoffTime, tzAbbrev } from "@/lib/datetime";

/** Client island: kickoff date/time in the user's timezone, plus venue.
 *  (Timezone is client-only; the rest of the match page is server-rendered.) */
export function LocalKickoff({ iso, venue }: { iso: string | null; venue: string | null }) {
  const { tz } = useTimezone();
  if (!iso && !venue) return null;
  return (
    <div className="mb-5 flex flex-wrap items-center justify-center gap-x-4 gap-y-1.5 text-sm text-muted">
      {iso && (
        <span className="inline-flex items-center gap-1.5 font-semibold text-foreground">
          <svg viewBox="0 0 24 24" className="h-4 w-4 text-lime-deep" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" strokeLinecap="round" />
          </svg>
          {dayHeading(iso, tz)} · {kickoffTime(iso, tz)}{" "}
          <span className="font-medium text-muted">{tzAbbrev(iso, tz)}</span>
        </span>
      )}
      {venue && (
        <span className="inline-flex items-center gap-1.5">
          <svg viewBox="0 0 24 24" className="h-4 w-4 text-lime-deep" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 21s-7-5.2-7-11a7 7 0 1 1 14 0c0 5.8-7 11-7 11Z" strokeLinejoin="round" />
            <circle cx="12" cy="10" r="2.5" />
          </svg>
          {venue}
        </span>
      )}
    </div>
  );
}
