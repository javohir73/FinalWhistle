"use client";

import { getGroups } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { COMPETITIONS, type CompetitionId } from "@/lib/sports";
import { StandingsTable } from "@/components/StandingsTable";
import { Eyebrow } from "@/components/Eyebrow";
import { ErrorState, Empty } from "@/components/States";
import type { ActiveTournament, Group } from "@/lib/types";

/** Canonical standings surface for league-format football competitions
 *  (epl/laliga/bundesliga). Dormant in P2: those comps are data-gated
 *  (COMPETITIONS[*].enabled === false), so page.tsx 404s until they ship --
 *  this is the forward-plumbing they light up for free. Mirrors GroupsClient's
 *  league path (a single Group holds the whole table) but paints the comp's
 *  CL/Europa/relegation zone stripes via COMPETITIONS[comp].zones. WC26 keeps
 *  its multi-group /groups grid and 404s here (see page.tsx). Frontend-only
 *  phase: when the single-league shape isn't present we degrade to an honest
 *  empty state rather than invent an endpoint. */
export function StandingsClient({
  comp,
  initialGroups,
  tournament,
}: {
  comp: CompetitionId;
  initialGroups?: Group[];
  tournament: ActiveTournament;
}) {
  const state = useFetch(getGroups, [], 30_000, initialGroups);
  const competition = COMPETITIONS[comp];
  const leagueMode =
    tournament.format === "league" && state.status === "success" && state.data.length === 1;

  return (
    <div>
      <header className="fade-up mb-8">
        <Eyebrow>{competition.label}</Eyebrow>
        <h1 className="mt-1 font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
          {competition.terms.standings}
        </h1>
        <p className="mt-2 max-w-xl text-muted">Live standings, updated as results come in.</p>
      </header>

      {state.status === "loading" && (
        <div className="glass rounded-2xl p-5 sm:p-6">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="skeleton mb-2 h-9 w-full rounded" />
          ))}
        </div>
      )}
      {state.status === "error" && <ErrorState message={state.message} onRetry={state.retry} />}
      {state.status === "success" &&
        (leagueMode ? (
          <div className="glass rounded-2xl p-5 sm:p-6">
            <StandingsTable standings={state.data[0].standings} zones={competition.zones} />
          </div>
        ) : (
          <Empty />
        ))}
    </div>
  );
}
