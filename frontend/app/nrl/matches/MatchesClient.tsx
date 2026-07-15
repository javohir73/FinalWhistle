"use client";

import { useEffect, useMemo, useState } from "react";
import { getNrlMatches } from "@/lib/api";
import { finishedRounds, liveNow, upcomingRounds } from "@/lib/nrlLive";
import type { NrlMatchesResponse } from "@/lib/types";
import { SportMatchCard } from "@/components/SportMatchCard";
import { cn } from "@/lib/utils";

type Filter = "Upcoming" | "Live" | "Finished";
const FILTERS: Filter[] = ["Upcoming", "Live", "Finished"];

const EMPTY: Record<Filter, string> = {
  Upcoming: "No upcoming fixtures yet.",
  Live: "No matches are live right now.",
  Finished: "No finished fixtures yet.",
};

/** Client island: segmented Upcoming/Live/Finished over the SSR-seeded
 *  fixtures. While any match is in its live window the list is refetched
 *  every 60s (scores land via the 15-min live poller); otherwise no polling. */
export function MatchesClient({ initial }: { initial: NrlMatchesResponse }) {
  const [fixtures, setFixtures] = useState(initial);
  const [filter, setFilter] = useState<Filter>("Upcoming");
  const [now, setNow] = useState(() => new Date());

  const live = useMemo(() => liveNow(fixtures.rounds, now), [fixtures, now]);

  useEffect(() => {
    if (live.length === 0) return;
    const tick = setInterval(() => {
      setNow(new Date());
      getNrlMatches().then(setFixtures).catch(() => {});
    }, 60_000);
    return () => clearInterval(tick);
  }, [live.length]);

  const groups = useMemo(
    () => (filter === "Finished" ? finishedRounds(fixtures.rounds) : upcomingRounds(fixtures.rounds, now)),
    [fixtures, filter, now],
  );

  const showStrip = filter !== "Finished" && live.length > 0;
  const empty =
    (filter === "Live" && live.length === 0) ||
    (filter !== "Live" && groups.length === 0 && !showStrip);

  return (
    <div>
      <h1 className="font-display text-2xl font-extrabold">NRL fixtures</h1>

      {/* Segmented control: Upcoming / Live / Finished — styling mirrors the
       *  WC26 MatchesClient island so the two fixtures pages match. */}
      <div className="mb-6 mt-4 flex gap-1 rounded-[14px] bg-surface-2 p-1">
        {FILTERS.map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => setFilter(f)}
            className={cn(
              "flex-1 rounded-[11px] px-3 py-2 text-sm font-semibold transition",
              f === filter
                ? "bg-surface text-foreground shadow-[0_1px_3px_rgba(18,40,25,0.1)]"
                : "text-muted hover:text-foreground",
            )}
          >
            {f}
          </button>
        ))}
      </div>

      {showStrip ? (
        <section>
          <div className="mb-3.5 flex items-center gap-2">
            <span className="h-2 w-2 animate-pulse rounded-full bg-loss" aria-hidden />
            <h2 className="font-display text-[11px] font-bold uppercase tracking-wider text-loss">
              Live now
            </h2>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {live.map(({ round, match }) => (
              <SportMatchCard key={`${round}-${match.match_no}`} match={match}
                eyebrow={`Round ${round ?? "TBC"} · LIVE`} season={fixtures.season} round={round} />
            ))}
          </div>
        </section>
      ) : null}

      {filter !== "Live" &&
        groups.map((g) => (
          <section key={String(g.round)} className="mt-8">
            <h2 className="font-display text-sm font-semibold uppercase tracking-wider text-muted">
              Round {g.round ?? "TBC"}
            </h2>
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              {g.matches.map((m) => (
                <SportMatchCard key={m.match_no} match={m}
                  eyebrow={`Round ${g.round ?? "TBC"}`} season={fixtures.season} round={g.round} />
              ))}
            </div>
          </section>
        ))}

      {empty ? <p className="mt-8 text-sm text-muted">{EMPTY[filter]}</p> : null}
    </div>
  );
}
