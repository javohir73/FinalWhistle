"use client";

import { useMemo, useState } from "react";
import { getUpcomingMatches } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { MatchCard } from "@/components/MatchCard";
import { Loading, ErrorState, Empty } from "@/components/States";

export default function HomePage() {
  const state = useFetch(getUpcomingMatches, []);
  const [group, setGroup] = useState("all");
  const [query, setQuery] = useState("");

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
    return okGroup && okQuery;
  });

  return (
    <div>
      {/* Hero */}
      <section className="fade-up mb-10">
        <div className="mb-3 inline-flex items-center gap-2 rounded-full chip px-3 py-1 text-xs font-medium text-muted">
          <span className="h-1.5 w-1.5 rounded-full bg-win shadow-[0_0_8px_hsl(var(--win))]" />
          Live model · {matches.length || 104} matches tracked
        </div>
        <h1 className="font-display text-4xl font-extrabold leading-[1.05] tracking-tight sm:text-6xl">
          The <span className="text-gradient">World Cup 2026</span>,
          <br className="hidden sm:block" /> predicted &amp; explained.
        </h1>
        <p className="mt-4 max-w-xl text-base text-muted">
          Calibrated AI forecasts for every match — win probabilities, scorelines,
          and the reasons behind each call. Built on Elo, Poisson, and 49,000
          historical results.
        </p>
      </section>

      {/* Filters */}
      <div
        className="fade-up mb-6 flex flex-col gap-3 sm:flex-row"
        style={{ animationDelay: "80ms" }}
      >
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
      </div>

      {state.status === "loading" && <Loading label="Loading predictions…" />}
      {state.status === "error" && <ErrorState message={state.message} />}
      {state.status === "success" &&
        (filtered.length === 0 ? (
          <Empty label="No matches match your filters." />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((m, i) => (
              <div
                key={m.match_id}
                className="fade-up"
                style={{ animationDelay: `${Math.min(i * 35, 500)}ms` }}
              >
                <MatchCard match={m} />
              </div>
            ))}
          </div>
        ))}
    </div>
  );
}
