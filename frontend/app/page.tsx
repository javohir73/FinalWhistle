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
      <div className="mb-6">
        <h1 className="text-2xl font-bold">FIFA World Cup 2026 predictions</h1>
        <p className="mt-1 text-foreground/60">
          Explainable AI match predictions, group odds, and team form.
        </p>
      </div>

      <div className="mb-5 flex flex-col gap-3 sm:flex-row">
        <input
          type="search"
          placeholder="Search team…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search team"
          className="w-full rounded-lg border border-border px-3 py-2 text-sm sm:max-w-xs"
        />
        <select
          value={group}
          onChange={(e) => setGroup(e.target.value)}
          aria-label="Filter by group"
          className="rounded-lg border border-border px-3 py-2 text-sm"
        >
          <option value="all">All groups</option>
          {groups.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
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
            {filtered.map((m) => (
              <MatchCard key={m.match_id} match={m} />
            ))}
          </div>
        ))}
    </div>
  );
}
