"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { getUpcomingMatches } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { useTimezone } from "@/lib/useTimezone";
import { dayKey, dayHeading, relativeDayLabel, tzCityLabel } from "@/lib/datetime";
import { isLiveNow } from "@/lib/liveLabel";
import { MatchCard } from "@/components/MatchCard";
import { LocationPicker } from "@/components/LocationPicker";
import { Loading, ErrorState, Empty } from "@/components/States";
import type { MatchSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

const TBC = "tbc";

// The segmented control maps onto the live fixture data: Upcoming = still to be
// played (scheduled, not yet live or final), Live = in-play right now, Finished =
// a real full-time result or an in_play the feed stranded past the live window
// (rendered as FT by the card). Finished is shown most-recent-first.
type Filter = "Upcoming" | "Live" | "Finished";
const FILTERS: Filter[] = ["Upcoming", "Live", "Finished"];

const isFinished = (m: MatchSummary) =>
  m.status === "finished" || (m.status === "in_play" && !isLiveNow(m));

export function MatchesClient({ initialMatches }: { initialMatches?: MatchSummary[] }) {
  // Poll every 30s so live in-game scores refresh automatically. Seeded from the
  // server so the first paint shows real fixtures, not a skeleton.
  const state = useFetch(getUpcomingMatches, [], 30_000, initialMatches);
  const { tz } = useTimezone();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("Upcoming");

  // Timezone pill → inline popover (no more jump to the full profile page).
  const [tzOpen, setTzOpen] = useState(false);
  const tzRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!tzOpen) return;
    const onClick = (e: MouseEvent) => {
      if (tzRef.current && !tzRef.current.contains(e.target as Node)) setTzOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setTzOpen(false);
    window.addEventListener("mousedown", onClick);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onClick);
      window.removeEventListener("keydown", onKey);
    };
  }, [tzOpen]);

  const matches = state.status === "success" ? state.data : [];

  // Search is always applied; the segmented control then narrows by state.
  const searched = matches.filter((m) => {
    const q = query.trim().toLowerCase();
    return (
      !q ||
      m.teams.home.toLowerCase().includes(q) ||
      m.teams.away.toLowerCase().includes(q)
    );
  });

  const filtered = searched.filter((m) => {
    if (filter === "Live") return isLiveNow(m);
    if (filter === "Finished") return isFinished(m);
    return !isLiveNow(m) && !isFinished(m); // Upcoming = still to be played
  });

  // Live games are pinned to the top on every view except Finished, so the
  // current match is never buried — even while you're browsing Upcoming.
  // isLiveNow (not a bare status check) keeps a match the feed left stuck
  // `in_play` from being pinned as "LIVE" forever — it falls into its day group.
  const liveMatches = (filter === "Finished" ? [] : searched.filter((m) => isLiveNow(m)))
    .sort((a, b) => (a.kickoff_utc ?? "").localeCompare(b.kickoff_utc ?? ""));
  const rest = filtered.filter((m) => !isLiveNow(m));

  // Bucket the non-live fixtures by local calendar day. Soonest-first, with any
  // undated fixtures last. Each day's eyebrow uses the relative label ("Today ·",
  // "Yesterday ·") where it applies, otherwise the absolute heading.
  const days = useMemo(() => {
    const byDay = new Map<string, MatchSummary[]>();
    for (const m of rest) {
      const key = m.kickoff_utc ? dayKey(m.kickoff_utc, tz) : TBC;
      let arr = byDay.get(key);
      if (!arr) byDay.set(key, (arr = []));
      arr.push(m);
    }
    // Soonest-first, except Finished — there you want the latest results on top.
    const dir = filter === "Finished" ? -1 : 1;
    return Array.from(byDay.entries()).sort(([a], [b]) => {
      if (a === TBC) return 1;
      if (b === TBC) return -1;
      return a < b ? -dir : dir;
    });
  }, [rest, tz, filter]);

  return (
    <div>
      <header className="mb-4 flex items-center justify-between gap-3">
        <h1 className="font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
          All <span className="text-lime-deep">fixtures</span>
        </h1>
        <div className="relative shrink-0" ref={tzRef}>
          <button
            type="button"
            onClick={() => setTzOpen((v) => !v)}
            aria-haspopup="dialog"
            aria-expanded={tzOpen}
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-3 py-1.5 text-xs font-semibold text-foreground transition hover:border-win/40"
          >
            <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 text-lime-deep" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 21s-7-5.2-7-11a7 7 0 1 1 14 0c0 5.8-7 11-7 11Z" strokeLinejoin="round" />
              <circle cx="12" cy="10" r="2.5" />
            </svg>
            {tzCityLabel(tz)}
          </button>
          {tzOpen && (
            <div
              role="dialog"
              aria-label="Choose your timezone"
              className="glass absolute right-0 z-50 mt-2 w-72 rounded-xl p-3 shadow-xl"
            >
              <LocationPicker />
            </div>
          )}
        </div>
      </header>

      <div className="relative mb-3">
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
          className="w-full rounded-xl border border-border bg-surface py-2.5 pl-9 pr-3 text-sm transition placeholder:text-muted/70 hover:border-win/40"
        />
      </div>

      {/* Segmented control: Upcoming / Live / Finished */}
      <div
        role="tablist"
        aria-label="Filter fixtures"
        className="mb-6 flex gap-1 rounded-[14px] bg-surface-2 p-1"
      >
        {FILTERS.map((f) => {
          const selected = filter === f;
          return (
            <button
              key={f}
              type="button"
              role="tab"
              aria-selected={selected}
              onClick={() => setFilter(f)}
              className={cn(
                "flex-1 rounded-[11px] px-3 py-2 text-sm font-semibold transition",
                selected
                  ? "bg-surface text-foreground shadow-[0_1px_3px_rgba(18,40,25,0.1)]"
                  : "text-muted hover:text-foreground",
              )}
            >
              {f}
            </button>
          );
        })}
      </div>

      {state.status === "loading" && <Loading label="Loading predictions…" />}
      {state.status === "error" && <ErrorState message={state.message} onRetry={state.retry} />}
      {state.status === "success" &&
        (filtered.length === 0 && liveMatches.length === 0 ? (
          <Empty label="No fixtures here yet." />
        ) : (
          <div className="space-y-9">
            {/* Pinned: live games, so the current match is the first thing you see. */}
            {liveMatches.length > 0 && (
              <section>
                <div className="mb-3.5 flex items-center gap-2">
                  <span className="h-2 w-2 animate-pulse rounded-full bg-loss" aria-hidden />
                  <h2 className="font-display text-[11px] font-bold uppercase tracking-wider text-loss">
                    Live now
                  </h2>
                </div>
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {liveMatches.map((m) => (
                    <MatchCard key={m.match_id} match={m} tz={tz} />
                  ))}
                </div>
              </section>
            )}

            {days.map(([key, dayMatches]) => {
              const iso = dayMatches[0].kickoff_utc;
              const rel = key === TBC || !iso ? null : relativeDayLabel(iso, tz);
              const heading =
                key === TBC || !iso
                  ? "Date to be confirmed"
                  : rel
                    ? `${rel} · ${dayHeading(iso, tz)}`
                    : dayHeading(iso, tz);
              return (
                <section key={key}>
                  <div className="mb-3.5">
                    <h2 className="font-display text-[11px] font-bold uppercase tracking-wider text-muted">
                      {heading}
                    </h2>
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
  );
}
