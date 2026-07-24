"use client";

import type { MatchSummary } from "@/lib/types";
import { isLiveNow } from "@/lib/liveLabel";
import { Eyebrow } from "@/components/Eyebrow";
import { MatchCard } from "@/components/MatchCard";
import { cn } from "@/lib/utils";

/** The Floodlight fixtures timeline (design/Floodlight Prototype.dc.html, Recon
 *  3 Screen 2): each day is a lime eyebrow heading over a vertical spine, with
 *  every kickoff hanging off the spine as a compact MatchCard. The spine is the
 *  prototype's dimmer hairline (`border-left:2px solid #1a251d`) -- `border-border`
 *  is the closest token, so we use it rather than mint a one-off. Each row wears
 *  an absolutely-positioned dot on the spine: rose (`border-loss`) when the match
 *  is live right now, otherwise the hairline color (`border-border`) -- the
 *  prototype's `dotColor` (live `#f6516b` else `#243028`). The dot is static;
 *  the live pulse lives on the card's own status util, so nothing here animates. */
export function TimelineSpine({
  days,
  tz,
}: {
  days: Array<{ key: string; heading: string; matches: MatchSummary[] }>;
  tz: string;
}) {
  return (
    <div className="space-y-6">
      {days.map((day) => (
        <section key={day.key}>
          <div className="mb-1.5">
            <Eyebrow tone="lime">{day.heading}</Eyebrow>
          </div>
          <div className="ml-[5px] flex flex-col gap-2 border-l-2 border-border pl-4">
            {day.matches.map((m) => (
              <div key={m.match_id} className="relative">
                <span
                  aria-hidden
                  className={cn(
                    "absolute left-[-23px] top-4 h-3 w-3 rounded-full border-2 bg-background",
                    isLiveNow(m) ? "border-loss" : "border-border",
                  )}
                />
                <MatchCard match={m} tz={tz} variant="compact" />
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
