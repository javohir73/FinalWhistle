"use client";

import { usePathname } from "next/navigation";
import { getGroups, getUpcomingMatches } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { GroupCard } from "@/components/GroupCard";
import { StandingsTable } from "@/components/StandingsTable";
import { ErrorState, Empty } from "@/components/States";
import { COMPETITIONS, competitionFromPathname } from "@/lib/sports";
import type { ActiveTournament, Group } from "@/lib/types";

export function GroupsClient({
  initialGroups,
  tournament,
}: {
  initialGroups?: Group[];
  tournament: ActiveTournament;
}) {
  const state = useFetch(getGroups, [], 30_000, initialGroups);
  // Match feed drives the per-group LIVE badge. Polled alongside groups; if it
  // fails or is still loading, matches stays empty and no badge shows.
  const matchesState = useFetch(getUpcomingMatches, [], 30_000);
  const matches = matchesState.status === "success" ? matchesState.data : undefined;
  // League-format standings paint the active competition's CL/Europa/relegation
  // zone stripes (Floodlight P2). Resolve it from the path so any wired league
  // gets the right bands; today's un-namespaced /groups falls back to WC26
  // (zones: []), which renders a plain league table.
  const pathname = usePathname() ?? "";

  // D1: a league is one Tournament + a single Group holding every team — show
  // it as one full-width table instead of the WC26 multi-group card grid.
  const leagueMode =
    tournament.format === "league" && state.status === "success" && state.data.length === 1;

  return (
    <div>
      <header className="fade-up mb-8">
        <h1 className="font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
          {leagueMode ? (
            tournament.name
          ) : (
            <>
              Group <span className="text-lime-deep">tables</span>
            </>
          )}
        </h1>
        <p className="mt-2 max-w-xl text-muted">
          {leagueMode
            ? "Live standings, updated as results come in."
            : "Live standings with each team's chance of finishing top two."}
        </p>
      </header>

      {state.status === "loading" && (
        <div className="grid gap-5 md:grid-cols-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="glass rounded-2xl p-5">
              <div className="skeleton mb-4 h-5 w-24 rounded" />
              {Array.from({ length: 4 }).map((_, j) => (
                <div key={j} className="skeleton mb-2 h-8 w-full rounded" />
              ))}
            </div>
          ))}
        </div>
      )}
      {state.status === "error" && <ErrorState message={state.message} onRetry={state.retry} />}
      {state.status === "success" &&
        (state.data.length === 0 ? (
          <Empty />
        ) : leagueMode ? (
          <div className="glass rounded-2xl p-5 sm:p-6">
            <StandingsTable
              standings={state.data[0].standings}
              zones={COMPETITIONS[competitionFromPathname(pathname)].zones}
            />
          </div>
        ) : (
          <div className="grid gap-5 md:grid-cols-2">
            {state.data.map((g, i) => (
              <GroupCard key={g.id} group={g} index={i} matches={matches} />
            ))}
          </div>
        ))}
    </div>
  );
}
