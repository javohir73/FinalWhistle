"use client";

import { useEffect, useMemo, useState } from "react";
import { getNrlMatches } from "@/lib/api";
import { finishedRounds, liveNow, upcomingRounds } from "@/lib/nrlLive";
import type { NrlMatchesResponse } from "@/lib/types";
import { MatchCard } from "@/components/MatchCard";
import { TimelineSpine } from "@/components/TimelineSpine";
import { nrlExpectedMargin, nrlMatchHref, nrlMatchToSummary } from "@/lib/nrlAdapters";
import { cn } from "@/lib/utils";

type Filter = "Upcoming" | "Live" | "Finished";
const FILTERS: Filter[] = ["Upcoming", "Live", "Finished"];

const EMPTY: Record<Filter, string> = {
  Upcoming: "No upcoming fixtures yet.",
  Live: "No matches are live right now.",
  Finished: "No finished fixtures yet.",
};

/** Client island: segmented Upcoming/Live/Finished over the SSR-seeded fixtures.
 *  A 30s local clock tick runs unconditionally so a match self-promotes into the
 *  live strip at kickoff even if none was live on first paint; the 60s data
 *  refetch (scores land via the 15-min live poller) stays gated on ≥1 live match. */
export function MatchesClient({ initial }: { initial: NrlMatchesResponse }) {
  const [fixtures, setFixtures] = useState(initial);
  const [filter, setFilter] = useState<Filter>("Upcoming");
  const [now, setNow] = useState(() => new Date());

  const live = useMemo(() => liveNow(fixtures.rounds, now), [fixtures, now]);

  // Clock tick: local only, always on — this is what detects a match entering or
  // leaving its live window, so it can't be gated behind `live.length` or a fixture
  // that kicks off after first paint would never flip the strip on.
  useEffect(() => {
    const tick = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(tick);
  }, []);

  // Data refetch: network, only while live — scores land via the 15-min live
  // poller, so there's nothing to gain from polling the API when nothing's on.
  useEffect(() => {
    if (live.length === 0) return;
    const tick = setInterval(() => {
      getNrlMatches().then(setFixtures).catch(() => {});
    }, 60_000);
    return () => clearInterval(tick);
  }, [live.length]);

  const groups = useMemo(
    () => (filter === "Finished" ? finishedRounds(fixtures.rounds) : upcomingRounds(fixtures.rounds, now)),
    [fixtures, filter, now],
  );

  // Per-card detail href + expected margin for every fixture in the visible
  // groups, keyed by match_id (= NrlMatch.id). Match ids are unique across
  // rounds, so one flat map feeds every day of the spine.
  const { cardHref, cardMargin } = useMemo(() => {
    const href: Record<number, string | null> = {};
    const margin: Record<number, number | null> = {};
    for (const g of groups) {
      for (const m of g.matches) {
        href[m.id] = nrlMatchHref(fixtures.season, g.round, m.match_no);
        margin[m.id] = nrlExpectedMargin(m);
      }
    }
    return { cardHref: href, cardMargin: margin };
  }, [groups, fixtures.season]);

  const showStrip = filter !== "Finished" && live.length > 0;
  const empty =
    (filter === "Live" && live.length === 0) ||
    (filter !== "Live" && groups.length === 0 && !showStrip);

  return (
    <div>
      <h1 className="font-display text-2xl font-extrabold">NRL fixtures</h1>

      {/* Segmented control: Upcoming / Live / Finished — styling mirrors the
       *  WC26 MatchesClient island so the two fixtures pages match. */}
      <div
        role="tablist"
        aria-label="Fixture filter"
        className="mb-6 mt-4 flex gap-1 rounded-[14px] bg-surface-2 p-1"
      >
        {FILTERS.map((f) => (
          <button
            key={f}
            type="button"
            role="tab"
            aria-selected={f === filter}
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

      {/* Live strip: keep the custom pulse eyebrow, but render each in-window
       *  match through the shared compact MatchCard (club badges, margin chip,
       *  detail link). Same idiom as the football MatchesClient live strip — a
       *  plain grid pinned above the spine, not itself a spine day. Liveness
       *  detection (nrlLive.liveNow) is unchanged. */}
      {showStrip ? (
        <section>
          <div className="mb-3.5 flex items-center gap-2">
            <span className="h-2 w-2 animate-pulse rounded-full bg-loss" aria-hidden />
            <h2 className="font-display text-[11px] font-bold uppercase tracking-wider text-loss">
              Live now
            </h2>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {live.map(({ round, match }) => (
              <MatchCard
                key={`${round}-${match.match_no}`}
                match={nrlMatchToSummary(match)}
                tz="Australia/Sydney"
                variant="compact"
                badge="club"
                href={nrlMatchHref(fixtures.season, round, match.match_no)}
                margin={nrlExpectedMargin(match)}
              />
            ))}
          </div>
        </section>
      ) : null}

      {/* Round sections fall down the shared Floodlight spine — one day group
       *  per round (heading arbitrary, so the round structure is preserved). */}
      {filter !== "Live" && groups.length > 0 ? (
        <div className="mt-8">
          <TimelineSpine
            days={groups.map((g) => ({
              key: `round-${g.round ?? "tbc"}`,
              heading: `Round ${g.round ?? "TBC"}`,
              matches: g.matches.map(nrlMatchToSummary),
            }))}
            tz="Australia/Sydney"
            badge="club"
            cardHref={cardHref}
            cardMargin={cardMargin}
          />
        </div>
      ) : null}

      {empty ? <p className="mt-8 text-sm text-muted">{EMPTY[filter]}</p> : null}
    </div>
  );
}
