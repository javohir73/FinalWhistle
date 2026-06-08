"use client";

import { useMemo, useState } from "react";
import { getUpcomingMatches } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { useFavorites } from "@/lib/useFavorites";
import { useTimezone } from "@/lib/useTimezone";
import { dayKey, dayHeading } from "@/lib/datetime";
import { MatchCard } from "@/components/MatchCard";
import { LocationPicker } from "@/components/LocationPicker";
import { Loading, ErrorState, Empty } from "@/components/States";
import type { MatchSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

const TBC = "tbc";

export default function MatchesPage() {
  // Poll every 30s so live in-game scores refresh automatically.
  const state = useFetch(getUpcomingMatches, [], 30_000);
  const { favorites, isFavorite } = useFavorites();
  const { tz } = useTimezone();
  const [group, setGroup] = useState("all");
  const [query, setQuery] = useState("");
  const [favOnly, setFavOnly] = useState(false);

  const matches = state.status === "success" ? state.data : [];
  const groups = useMemo(
    () => Array.from(new Set(matches.map((m) => m.group).filter(Boolean))).sort() as string[],
    [matches],
  );

  const filtered = matches.filter((m) => {
    const okGroup = group === "all" || m.group === group;
    const q = query.trim().toLowerCase();
    const okQuery =
      !q ||
      m.teams.home.toLowerCase().includes(q) ||
      m.teams.away.toLowerCase().includes(q);
    const okFav = !favOnly || isFavorite(m.teams.home) || isFavorite(m.teams.away);
    return okGroup && okQuery && okFav;
  });

  // Bucket matches by their local calendar day (soonest first; undated last).
  const days = useMemo(() => {
    const byDay = new Map<string, MatchSummary[]>();
    for (const m of filtered) {
      const key = m.kickoff_utc ? dayKey(m.kickoff_utc, tz) : TBC;
      let arr = byDay.get(key);
      if (!arr) byDay.set(key, (arr = []));
      arr.push(m);
    }
    return Array.from(byDay.entries()).sort(([a], [b]) => {
      if (a === TBC) return 1;
      if (b === TBC) return -1;
      return a < b ? -1 : 1;
    });
  }, [filtered, tz]);

  return (
    <div>
      <header className="mb-6">
        <h1 className="font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
          Match predictions
        </h1>
        <p className="mt-2 text-muted">
          Every fixture by kickoff — win probabilities, scorelines, time, and venue.
        </p>
      </header>

      <div className="mb-6">
        <LocationPicker />
      </div>

      {/* Filters */}
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative w-full sm:max-w-xs">
          <svg
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
            viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          >
            <circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" />
          </svg>
          <input
            type="search"
            placeholder="Search a team…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search team"
            className="w-full rounded-xl border border-border bg-surface/60 py-2.5 pl-9 pr-3 text-sm outline-none transition placeholder:text-muted/60 focus:border-win/50 focus:ring-2 focus:ring-win/20"
          />
        </div>
        <select
          value={group}
          onChange={(e) => setGroup(e.target.value)}
          aria-label="Filter by group"
          className="rounded-xl border border-border bg-surface/60 px-3 py-2.5 text-sm outline-none transition focus:border-win/50 focus:ring-2 focus:ring-win/20"
        >
          <option value="all">All groups</option>
          {groups.map((g) => (
            <option key={g} value={g}>{g}</option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => setFavOnly((v) => !v)}
          aria-pressed={favOnly}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-xl border px-3 py-2.5 text-sm transition",
            favOnly
              ? "border-gold/40 bg-gold/10 text-gold"
              : "border-border bg-surface/60 text-muted hover:text-foreground",
          )}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill={favOnly ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinejoin="round">
            <path d="M12 2l3 6.5 7 .7-5.2 4.8 1.5 6.9L12 17.8 5.7 20.9l1.5-6.9L2 9.2l7-.7z" />
          </svg>
          Favorites{favorites.length ? ` (${favorites.length})` : ""}
        </button>
      </div>

      {state.status === "loading" && <Loading label="Loading predictions…" />}
      {state.status === "error" && <ErrorState message={state.message} />}
      {state.status === "success" &&
        (filtered.length === 0 ? (
          <Empty
            label={
              favOnly && favorites.length === 0
                ? "Star a team to build your favorites feed."
                : "No matches match your filters."
            }
          />
        ) : (
          <div className="space-y-9">
            {days.map(([key, dayMatches]) => (
              <section key={key}>
                <div className="mb-3.5 flex items-center gap-3">
                  <h2 className="font-display text-sm font-bold uppercase tracking-wider text-foreground">
                    {key === TBC
                      ? "Date to be confirmed"
                      : dayHeading(dayMatches[0].kickoff_utc!, tz)}
                  </h2>
                  <span className="h-px flex-1 bg-border/60" />
                  <span className="font-display text-xs font-semibold text-muted">
                    {dayMatches.length} {dayMatches.length === 1 ? "match" : "matches"}
                  </span>
                </div>
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {dayMatches.map((m) => (
                    <MatchCard key={m.match_id} match={m} tz={tz} />
                  ))}
                </div>
              </section>
            ))}
          </div>
        ))}
    </div>
  );
}
