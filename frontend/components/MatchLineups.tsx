"use client";

import { getMatchLineups } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { ErrorState } from "@/components/States";
import { FormationPitch } from "@/components/FormationPitch";
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

  // Available, but the requested side may still be missing (e.g. only one team
  // confirmed): fall through to the placeholder rather than rendering nothing.
  const teams: TeamLineup[] = side
    ? ([side === "home" ? data.home : data.away].filter(Boolean) as TeamLineup[])
    : ([data.home, data.away].filter(Boolean) as TeamLineup[]);

  if (teams.length === 0) {
    return (
      <p className="glass rounded-2xl p-6 text-center text-sm text-muted">
        Lineup not available yet.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className={side ? "" : "grid gap-4 sm:grid-cols-2"}>
        {teams.map((t, i) => (
          <div key={`${t.team}-${i}`} className="glass rounded-2xl p-4">
            <FormationPitch lineup={t} />
            <Bench players={t.bench} />
          </div>
        ))}
      </div>
      <Attribution fetchedAt={data.fetched_at} />
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
