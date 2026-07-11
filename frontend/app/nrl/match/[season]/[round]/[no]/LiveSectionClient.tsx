"use client";

import { pct } from "@/lib/format";
import type { NrlLive } from "@/lib/types";

/** Presentational half of the Wave 3 "live" section: the sticky pinned
 *  banner (only while `live.status === "live"`) plus the scoreboard/events
 *  card. Pure function of already-fetched data — LiveSection.tsx owns the
 *  60s-polling fetch and hands the resolved payload down here. The banner
 *  uses sticky positioning and is rendered as a sibling of the card (not
 *  nested inside it), so "live pinned first" holds regardless of where
 *  sections.ts places this section in the stacked-card DOM order. */
export function LiveSectionClient({
  home, away, live,
}: { home: string; away: string; live: NrlLive }) {
  const isLive = live.status === "live";

  return (
    <>
      {isLive && (
        <div
          className="sticky top-14 z-40 mb-4 flex items-center justify-between gap-3 rounded-xl border border-border bg-surface/95 px-4 py-2 text-sm backdrop-blur"
          aria-live="polite"
        >
          <span className="flex items-center gap-1.5 font-semibold text-foreground">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-loss" aria-hidden />
            LIVE {live.minute}&apos;
          </span>
          <span className="tabular-nums text-foreground">
            {home} {live.score_home}&ndash;{live.score_away} {away}
          </span>
          <span className="font-bold tabular-nums text-lime-deep">{pct(live.live_home_prob)}</span>
        </div>
      )}
      <div className="glass rounded-2xl p-6">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="font-display text-lg font-bold text-foreground">{isLive ? "Live" : "Final"}</h2>
          {isLive && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-loss/15 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-loss">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" aria-hidden />
              Live &middot; {live.minute}&apos;
            </span>
          )}
        </div>
        <div className="flex items-center justify-center gap-6">
          <TeamScore name={home} score={live.score_home} />
          <span className="font-display text-2xl font-extrabold tabular-nums text-muted">&ndash;</span>
          <TeamScore name={away} score={live.score_away} />
        </div>
        <p className="mt-4 text-center text-sm font-semibold text-lime-deep">
          {home} win chance &middot; {pct(live.live_home_prob)}
        </p>
        {live.events.length > 0 && (
          <ul className="mt-5 space-y-1.5 border-t border-border pt-4 text-sm">
            {live.events.map((e, i) => (
              <li key={i} className="flex items-center justify-between gap-2">
                <span className="text-muted">
                  {e.minute}&apos; {e.team === "home" ? home : away}
                  {e.player ? ` — ${e.player}` : ""}
                </span>
                <span className="tabular-nums text-foreground">{pct(e.prob_after)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

function TeamScore({ name, score }: { name: string; score: number | null }) {
  return (
    <div className="flex flex-col items-center gap-1 text-center">
      <span className="font-display text-sm font-bold">{name}</span>
      <span className="font-display text-2xl font-extrabold tabular-nums">{score ?? "–"}</span>
    </div>
  );
}
