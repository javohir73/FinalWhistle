"use client";

import { getMatchLineups } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { ErrorState } from "@/components/States";
import { FormationPitch } from "@/components/FormationPitch";
import { MatchPitch } from "@/components/MatchPitch";
import { Flag } from "@/components/Flag";
import type { LineupPlayer, MatchLineups as MatchLineupsData, TeamLineup } from "@/lib/types";

/** Client island: lazily fetches a match's official lineups and renders each
 *  team's formation pitch + bench + coach. Degrades honestly — when the API
 *  returns `{ available: false }` (future fixture, no key, provider error) it
 *  shows the provided placeholder message, and a fetch failure shows a "Try
 *  again" using the shared useFetch / ErrorState pattern. Display-only: lineups
 *  never feed the prediction model.
 *
 *  Pass `side` to render only one team's XI (used by the team dashboard's
 *  "Last XI"); omit it to show both home and away (the match-detail view). */
export function MatchLineups({
  matchId,
  side,
}: {
  matchId: number;
  side?: "home" | "away";
}) {
  const state = useFetch<MatchLineupsData>(() => getMatchLineups(matchId), [matchId]);

  if (state.status === "loading") {
    return <LineupsSkeleton both={!side} />;
  }
  if (state.status === "error") {
    // Lineups are display-only — don't blame "the prediction service" here.
    return (
      <ErrorState
        message={state.message}
        onRetry={state.retry}
        hint="Couldn't load lineups — try again in a moment."
      />
    );
  }

  const data = state.data;

  if (!data.available) {
    return (
      <p className="glass rounded-2xl p-6 text-center text-sm text-muted">
        {data.message ?? "Lineups are announced ~40 minutes before kickoff."}
      </p>
    );
  }

  const notYet = (
    <p className="glass rounded-2xl p-6 text-center text-sm text-muted">
      Lineup not available yet.
    </p>
  );

  // Team-dashboard view: just this side's XI on a single-team pitch.
  if (side) {
    const team = side === "home" ? data.home : data.away;
    if (!team) return notYet;
    return (
      <div className="space-y-4">
        <div className="glass rounded-2xl p-4">
          <FormationPitch lineup={team} />
          <Bench players={team.bench} />
        </div>
        <Attribution fetchedAt={data.fetched_at} />
      </div>
    );
  }

  // Match view: both teams on ONE shared pitch (home top / away bottom).
  if (data.home && data.away) {
    return (
      <div className="space-y-4">
        <div className="glass rounded-2xl p-4">
          <MatchPitch home={data.home} away={data.away} />
        </div>
        <TwoTeamBench home={data.home} away={data.away} />
        <Attribution fetchedAt={data.fetched_at} />
      </div>
    );
  }

  // Only one side confirmed so far — show that team's single pitch.
  const only = data.home ?? data.away;
  if (!only) return notYet;
  return (
    <div className="space-y-4">
      <div className="glass rounded-2xl p-4">
        <FormationPitch lineup={only} />
        <Bench players={only.bench} />
      </div>
      <Attribution fetchedAt={data.fetched_at} />
    </div>
  );
}

/** Both teams' substitutes, side by side (the match view's combined bench). */
function TwoTeamBench({ home, away }: { home: TeamLineup; away: TeamLineup }) {
  if (home.bench.length === 0 && away.bench.length === 0) return null;
  return (
    <div className="glass rounded-2xl p-4">
      <p className="mb-2.5 text-center text-[11px] font-semibold uppercase tracking-wider text-muted">
        Bench
      </p>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1">
        <BenchColumn team={home} />
        <BenchColumn team={away} />
      </div>
    </div>
  );
}

function BenchColumn({ team }: { team: TeamLineup }) {
  return (
    <div className="min-w-0">
      <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-foreground">
        <Flag team={team.team} size={14} />
        <span className="truncate">{team.team}</span>
      </p>
      <ul className="space-y-0.5 text-xs text-foreground/90">
        {team.bench.length === 0 ? (
          <li className="text-muted">—</li>
        ) : (
          team.bench.map((p, i) => (
            <li key={`${p.number ?? "x"}-${p.name}-${i}`} className="truncate tabular-nums">
              {p.number != null && <span className="mr-1 font-semibold text-muted">{p.number}</span>}
              {p.name}
            </li>
          ))
        )}
      </ul>
    </div>
  );
}

function Bench({ players }: { players: LineupPlayer[] }) {
  if (!players || players.length === 0) return null;
  return (
    <div className="mt-3 border-t border-border pt-3">
      <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
        Bench
      </p>
      <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-foreground/90">
        {players.map((p, i) => (
          <li key={`${p.number ?? "x"}-${p.name}-${i}`} className="tabular-nums">
            {p.number != null && (
              <span className="mr-1 font-semibold text-muted">{p.number}</span>
            )}
            {p.name}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Honest source + freshness line. Always names the provider; appends the
 *  fetched time when known. */
function Attribution({ fetchedAt }: { fetchedAt: string | null }) {
  return (
    <p className="text-center text-[11px] leading-relaxed text-muted">
      Official lineup — via API-Football
      {fetchedAt ? <> · fetched {formatFetched(fetchedAt)}</> : null}
    </p>
  );
}

/** Format the fetched-at ISO timestamp. Backend timestamps may be naive UTC
 *  (no offset) — tag as UTC so the time doesn't shift, mirroring the match page's
 *  fmtUpdated. Falls back to the raw date on any parse error. */
function formatFetched(iso: string): string {
  const utc = /[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`;
  try {
    return new Intl.DateTimeFormat("en-GB", {
      day: "numeric",
      month: "short",
      hour: "numeric",
      minute: "2-digit",
    }).format(new Date(utc));
  } catch {
    return iso.slice(0, 10);
  }
}

/** Lightweight skeleton matching the lineup card shape (one card per side). */
function LineupsSkeleton({ both }: { both: boolean }) {
  return (
    <div
      role="status"
      aria-label="Loading lineups…"
      className={both ? "grid gap-4 sm:grid-cols-2" : ""}
    >
      {Array.from({ length: both ? 2 : 1 }).map((_, i) => (
        <div key={i} className="glass rounded-2xl p-4">
          <div className="skeleton mb-3 h-4 w-24 rounded" />
          <div className="skeleton h-48 w-full rounded-2xl" />
        </div>
      ))}
    </div>
  );
}
