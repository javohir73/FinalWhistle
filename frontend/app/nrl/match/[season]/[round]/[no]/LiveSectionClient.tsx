"use client";

import { createPortal } from "react-dom";
import { pct } from "@/lib/format";
import type { NrlLive } from "@/lib/types";

/** Presentational half of the Wave 3 "live" section: the in-flow
 *  scoreboard/events card, plus — only while `live.status === "live"` — a
 *  compact fixed strip (minute + score + live win prob) pinned just below
 *  the app header (`top-14`, under the header's z-50) so a live match is
 *  visible the moment the page loads, regardless of where sections.ts
 *  places this card in the stacked DOM order. The strip is portalled to
 *  document.body: the page's `.fade-up` wrapper animates with fill-mode
 *  `both`, ending on `transform: translateY(0)`, and any non-`none`
 *  transform makes that ancestor the containing block for `position: fixed`
 *  descendants — a strip rendered in place would anchor to the wrapper and
 *  scroll away with it instead of pinning to the viewport. Pure function of
 *  already-fetched data — LiveSection.tsx owns the 60s-polling fetch. */
export function LiveSectionClient({
  home, away, live,
}: { home: string; away: string; live: NrlLive }) {
  const isLive = live.status === "live";

  const pinnedStrip =
    isLive && typeof document !== "undefined"
      ? createPortal(
          <div
            className="pointer-events-none fixed inset-x-0 top-14 z-40 px-4"
            role="status"
            aria-label="Live score"
          >
            <div className="pointer-events-auto mx-auto flex max-w-2xl items-center justify-between gap-3 rounded-xl border border-border bg-surface/95 px-4 py-2 text-sm shadow-xl backdrop-blur">
              <span className="flex items-center gap-1.5 font-semibold text-foreground">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-loss" aria-hidden />
                LIVE {live.minute}&apos;
              </span>
              <span className="tabular-nums text-foreground">
                {home} {live.score_home}&ndash;{live.score_away} {away}
              </span>
              <span className="font-bold tabular-nums text-lime-deep">{pct(live.live_home_prob)}</span>
            </div>
          </div>,
          document.body,
        )
      : null;

  return (
    <>
      {pinnedStrip}
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
