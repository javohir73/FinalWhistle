"use client";

import { useEffect, useMemo, useState } from "react";
import { getUpcomingMatches } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { useFavorites } from "@/lib/useFavorites";
import { useTimezone } from "@/lib/useTimezone";
import { useSelectedCountry } from "@/lib/useSelectedCountry";
import { dayKey, dayHeading, relativeDayLabel } from "@/lib/datetime";
import { MatchCard } from "@/components/MatchCard";
import { Flag } from "@/components/Flag";
import { LocationPicker } from "@/components/LocationPicker";
import { LiveStatusBadge } from "@/components/LiveStatusBadge";
import { Loading, ErrorState, Empty } from "@/components/States";
import type { MatchSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

const TBC = "tbc";

type SortKey = "kickoff" | "confidence" | "upset" | "winprob";
const SORTS: { value: SortKey; label: string }[] = [
  { value: "kickoff", label: "Sort: Kickoff" },
  { value: "winprob", label: "Sort: Highest win probability" },
  { value: "confidence", label: "Sort: Confidence" },
  { value: "upset", label: "Sort: Biggest upset chance" },
];

const CONF_RANK: Record<string, number> = { High: 3, Medium: 2, Low: 1 };
// Favorite's win probability (strongest pick) vs the underdog's win probability
// (how live an upset is). Draw isn't a "winner", so both ignore it. Fixtures
// without a prediction yet (probabilities null) score lowest and sink to the end.
const winProb = (m: MatchSummary) =>
  m.probabilities ? Math.max(m.probabilities.home_win, m.probabilities.away_win) : -1;
const upsetProb = (m: MatchSummary) =>
  m.probabilities ? Math.min(m.probabilities.home_win, m.probabilities.away_win) : -1;
const confScore = (m: MatchSummary) =>
  m.probabilities ? (CONF_RANK[m.confidence ?? ""] ?? 0) + winProb(m) : -1;

export function MatchesClient({ initialMatches }: { initialMatches?: MatchSummary[] }) {
  // Poll every 30s so live in-game scores refresh automatically. Seeded from the
  // server so the first paint shows real fixtures, not a skeleton.
  const state = useFetch(getUpcomingMatches, [], 30_000, initialMatches);
  const { favorites, isFavorite } = useFavorites();
  const { tz } = useTimezone();
  const { selection, hydrated } = useSelectedCountry();
  const [group, setGroup] = useState("all");
  const [query, setQuery] = useState("");
  const [favOnly, setFavOnly] = useState(false);
  const [sort, setSort] = useState<SortKey>("kickoff");
  // Country-first: when a nation is being followed, default the list to its
  // fixtures. The user can flip to all matches; with no selection this is inert.
  // Persisted in sessionStorage so opening a match and coming back doesn't snap
  // the list back to country-only (component state resets on navigation).
  const FOCUS_KEY = "finalwhistle:matches-country-focus:v1";
  const [countryFocus, setCountryFocusState] = useState(true);
  useEffect(() => {
    try {
      const stored = window.sessionStorage.getItem(FOCUS_KEY);
      if (stored !== null) setCountryFocusState(stored === "1");
    } catch {
      /* storage unavailable — keep the default */
    }
  }, []);
  const setCountryFocus = (updater: (v: boolean) => boolean) =>
    setCountryFocusState((v) => {
      const next = updater(v);
      try {
        window.sessionStorage.setItem(FOCUS_KEY, next ? "1" : "0");
      } catch {
        /* non-fatal */
      }
      return next;
    });

  const matches = state.status === "success" ? state.data : [];
  const country = hydrated && selection ? selection.team : null;
  const focused = !!country && countryFocus;
  const hasActiveFilters = group !== "all" || query.trim() !== "" || favOnly || focused;
  const clearFilters = () => {
    setGroup("all");
    setQuery("");
    setFavOnly(false);
    setCountryFocus(() => false);
  };
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
    const okCountry =
      !focused || m.teams.home === country || m.teams.away === country;
    return okGroup && okQuery && okFav && okCountry;
  });

  // Live games are pinned to the top so you never scroll to find the current
  // match; everything else flows into the day/ranked views below.
  const liveMatches = filtered
    .filter((m) => m.status === "in_play")
    .sort((a, b) => (a.kickoff_utc ?? "").localeCompare(b.kickoff_utc ?? ""));
  const rest = filtered.filter((m) => m.status !== "in_play");

  // Bucket the rest by local calendar day, ordered now-first: today + upcoming
  // (soonest first), then past days (most recent first), undated last. So the
  // board opens on current/recent action, not the tournament's first fixtures.
  const days = useMemo(() => {
    const byDay = new Map<string, MatchSummary[]>();
    for (const m of rest) {
      const key = m.kickoff_utc ? dayKey(m.kickoff_utc, tz) : TBC;
      let arr = byDay.get(key);
      if (!arr) byDay.set(key, (arr = []));
      arr.push(m);
    }
    const todayKey = dayKey(new Date().toISOString(), tz);
    return Array.from(byDay.entries()).sort(([a], [b]) => {
      if (a === TBC) return 1;
      if (b === TBC) return -1;
      const aPast = a < todayKey;
      const bPast = b < todayKey;
      if (aPast !== bPast) return aPast ? 1 : -1; // today + upcoming before past
      if (!aPast) return a < b ? -1 : 1;          // today + upcoming: soonest first
      return a < b ? 1 : -1;                      // past: most recent first
    });
  }, [rest, tz]);

  // Metric sorts produce a single ranked list (highest first); kickoff keeps the
  // day-bucketed view above. Live games stay pinned regardless of sort.
  const ranked = useMemo(() => {
    if (sort === "kickoff") return [];
    const score =
      sort === "confidence" ? confScore : sort === "upset" ? upsetProb : winProb;
    return [...rest].sort((a, b) => score(b) - score(a));
  }, [rest, sort]);

  return (
    <div>
      <header className="mb-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h1 className="font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
            Match predictions
          </h1>
          <LiveStatusBadge />
        </div>
        <p className="mt-2 text-muted">
          Live now, upcoming fixtures, and recent results — win probabilities, scorelines, time, and venue.
        </p>
      </header>

      {country && (
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-win/30 bg-win/5 px-4 py-3">
          <span className="flex items-center gap-2.5 text-sm">
            <Flag team={country} size={26} />
            <span className="text-muted">
              {focused ? "Showing fixtures for" : "Following"}{" "}
              <span className="font-semibold text-foreground">{country}</span>
            </span>
          </span>
          <button
            type="button"
            onClick={() => setCountryFocus((v) => !v)}
            className="rounded-lg border border-border bg-surface/60 px-3 py-1.5 text-sm font-medium text-foreground transition hover:border-win/40"
          >
            {focused ? "Show all matches" : `Show only ${country}`}
          </button>
        </div>
      )}

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
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
          aria-label="Sort matches"
          className="rounded-xl border border-border bg-surface/60 px-3 py-2.5 text-sm outline-none transition focus:border-win/50 focus:ring-2 focus:ring-win/20"
        >
          {SORTS.map((s) => (
            <option key={s.value} value={s.value}>{s.label}</option>
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
          favOnly && favorites.length === 0 ? (
            <Empty label="Star a team to build your favorites feed." />
          ) : (
            <Empty
              label="No matches match your filters."
              action={
                hasActiveFilters ? (
                  <button
                    type="button"
                    onClick={clearFilters}
                    className="rounded-lg border border-border bg-surface/60 px-3 py-1.5 text-sm font-medium text-foreground transition hover:border-win/40"
                  >
                    Clear filters
                  </button>
                ) : undefined
              }
            />
          )
        ) : (
          <div className="space-y-9">
            {/* Pinned: live games, so the current match is the first thing you see. */}
            {liveMatches.length > 0 && (
              <section>
                <div className="mb-3.5 flex items-center gap-3">
                  <h2 className="flex items-center gap-2 font-display text-sm font-bold uppercase tracking-wider text-loss">
                    <span className="h-2 w-2 animate-pulse rounded-full bg-loss" aria-hidden />
                    Live now
                  </h2>
                  <span className="h-px flex-1 bg-loss/30" />
                  <span className="font-display text-xs font-semibold text-muted">
                    {liveMatches.length} {liveMatches.length === 1 ? "match" : "matches"}
                  </span>
                </div>
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {liveMatches.map((m) => (
                    <MatchCard key={m.match_id} match={m} tz={tz} />
                  ))}
                </div>
              </section>
            )}

            {rest.length > 0 &&
              (sort !== "kickoff" ? (
                <section>
                  <div className="mb-3.5 flex items-center gap-3">
                    <h2 className="font-display text-sm font-bold uppercase tracking-wider text-foreground">
                      {SORTS.find((s) => s.value === sort)?.label.replace("Sort: ", "")}
                    </h2>
                    <span className="h-px flex-1 bg-border/60" />
                    <span className="font-display text-xs font-semibold text-muted">
                      {ranked.length} {ranked.length === 1 ? "match" : "matches"}
                    </span>
                  </div>
                  <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    {ranked.map((m) => (
                      <MatchCard key={m.match_id} match={m} tz={tz} />
                    ))}
                  </div>
                </section>
              ) : (
                <div className="space-y-9">
                  {days.map(([key, dayMatches]) => {
                    const rel =
                      key === TBC ? null : relativeDayLabel(dayMatches[0].kickoff_utc!, tz);
                    return (
                    <section key={key}>
                      <div className="mb-3.5 flex items-center gap-3">
                        {rel && (
                          <span
                            className={`rounded-full px-2 py-0.5 font-display text-[11px] font-bold uppercase tracking-wide ring-1 ${
                              rel === "Today"
                                ? "bg-win/15 text-win ring-win/30"
                                : "bg-surface text-muted ring-border/60"
                            }`}
                          >
                            {rel}
                          </span>
                        )}
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
                    );
                  })}
                </div>
              ))}
          </div>
        ))}
    </div>
  );
}
