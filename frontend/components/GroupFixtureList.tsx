"use client";

import Link from "next/link";
import { useTimezone } from "@/lib/useTimezone";
import { Flag } from "@/components/Flag";
import { formatScore } from "@/lib/format";
import { isLiveNow, liveLabel } from "@/lib/liveLabel";
import { kickoffTime, tzAbbrev } from "@/lib/datetime";
import type { MatchSummary } from "@/lib/types";

/** Client island: the group's fixtures as compact light rows in the user's
 *  timezone (kickoff time is client-only; the rest of the group page is
 *  server-rendered). Each row links to the match and surfaces the model's
 *  predicted scoreline as an "AI: {score}" hint. */
export function GroupFixtureList({ matches }: { matches: MatchSummary[] }) {
  const { tz } = useTimezone();
  if (matches.length === 0) {
    return <p className="text-sm text-muted">Fixtures will appear once the draw is finalized.</p>;
  }
  return (
    <div className="space-y-2.5">
      {matches.map((m) => (
        <FixtureRow key={m.match_id} match={m} tz={tz} />
      ))}
    </div>
  );
}

function FixtureRow({ match, tz }: { match: MatchSummary; tz: string }) {
  const { teams, predicted_score } = match;
  const live = isLiveNow(match);
  const finished = match.status === "finished" || (match.status === "in_play" && !live);
  const hasScore = match.score_home != null && match.score_away != null;

  return (
    <Link
      href={`/match/${match.match_id}`}
      className={`card-hover glass group flex items-center gap-3 rounded-2xl p-3.5 ${
        live ? "ring-1 ring-loss/40" : ""
      }`}
    >
      <span className="flex shrink-0 -space-x-1.5">
        <Flag team={teams.home} size={26} />
        <Flag team={teams.away} size={26} />
      </span>

      <span className="min-w-0 flex-1">
        <span className="block truncate font-display text-sm font-bold tracking-tight">
          {teams.home} <span className="font-normal text-muted">v</span> {teams.away}
        </span>
        <span className="mt-0.5 block truncate text-xs text-muted">
          {live ? (
            <span className="inline-flex items-center gap-1.5 font-semibold text-loss">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-loss" aria-hidden />
              {liveLabel(match)}
            </span>
          ) : finished ? (
            <span className="font-semibold text-muted">Full time</span>
          ) : match.kickoff_utc ? (
            <>
              {kickoffTime(match.kickoff_utc, tz)}{" "}
              <span className="text-muted/80">{tzAbbrev(match.kickoff_utc, tz)}</span>
            </>
          ) : (
            "Kickoff to be confirmed"
          )}
        </span>
      </span>

      {(live || finished) && hasScore ? (
        <span className="shrink-0 font-display text-base font-extrabold tabular-nums text-foreground">
          {formatScore(match.score_home, match.score_away)}
        </span>
      ) : predicted_score ? (
        <span className="inline-flex shrink-0 items-center rounded-md bg-surface-2 px-2 py-0.5 font-display text-sm font-bold tabular-nums text-foreground">
          <span className="mr-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted">AI</span>
          {formatScore(predicted_score.home, predicted_score.away)}
        </span>
      ) : null}

      <span className="shrink-0 text-lime-deep transition group-hover:translate-x-0.5" aria-hidden>
        →
      </span>
    </Link>
  );
}
