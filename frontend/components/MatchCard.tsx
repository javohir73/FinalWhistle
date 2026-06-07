import Link from "next/link";
import type { MatchSummary } from "@/lib/types";
import { formatScore } from "@/lib/format";
import { kickoffTime, tzAbbrev } from "@/lib/datetime";
import { ProbabilityBar } from "./ProbabilityBar";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { Flag } from "./Flag";
import { FavoriteStar } from "./FavoriteStar";

/** The core dashboard card: matchup, predicted winner, W/D/L bar, score.
 *  When `tz` is given, kickoff time is shown in the user's local timezone. */
export function MatchCard({ match, tz }: { match: MatchSummary; tz?: string }) {
  const { teams, probabilities, predicted_score, confidence, predicted_winner } = match;
  const venue = [match.venue, match.venue_city].filter(Boolean).join(" · ");

  return (
    <Link
      href={`/match/${match.match_id}`}
      className="card-hover glass group block rounded-2xl p-4 focus:outline-none focus-visible:ring-2 focus-visible:ring-win/50"
    >
      <div className="mb-3 flex items-center justify-between">
        <span className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
          {match.group ?? match.stage}
        </span>
        {confidence && <ConfidenceBadge level={confidence} />}
      </div>

      {(match.kickoff_utc || venue) && (
        <div className="mb-3.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
          {match.kickoff_utc && tz && (
            <span className="inline-flex items-center gap-1.5 font-semibold text-win">
              <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" strokeLinecap="round" />
              </svg>
              {kickoffTime(match.kickoff_utc, tz)}
              <span className="font-medium text-muted">{tzAbbrev(match.kickoff_utc, tz)}</span>
            </span>
          )}
          {venue && (
            <span className="inline-flex min-w-0 items-center gap-1.5">
              <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 shrink-0" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 21s-7-5.2-7-11a7 7 0 1 1 14 0c0 5.8-7 11-7 11Z" strokeLinejoin="round" />
                <circle cx="12" cy="10" r="2.5" />
              </svg>
              <span className="truncate">{venue}</span>
            </span>
          )}
        </div>
      )}

      <div className="mb-4 space-y-2.5">
        <TeamRow name={teams.home} />
        <TeamRow name={teams.away} />
      </div>

      {probabilities ? (
        <ProbabilityBar
          probabilities={probabilities}
          homeLabel={teams.home}
          awayLabel={teams.away}
        />
      ) : (
        <p className="text-sm text-muted">Prediction pending…</p>
      )}

      <div className="mt-4 flex items-center justify-between border-t border-border/60 pt-3 text-sm">
        <span className="text-muted">
          Winner{" "}
          <strong className="font-semibold text-foreground">
            {predicted_winner ?? "—"}
          </strong>
        </span>
        {predicted_score && (
          <span className="chip rounded-md px-2 py-0.5 font-display text-sm font-bold tabular-nums text-foreground">
            {formatScore(predicted_score.home, predicted_score.away)}
          </span>
        )}
      </div>
    </Link>
  );
}

function TeamRow({ name }: { name: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <Flag team={name} size={24} />
      <span className="flex-1 font-display text-[15px] font-semibold tracking-tight">
        {name}
      </span>
      <FavoriteStar team={name} />
    </div>
  );
}
