"use client";

import Link from "next/link";
import type { MatchSummary } from "@/lib/types";
import { formatScore } from "@/lib/format";
import { liveLabel } from "@/lib/liveLabel";
import { predictionVerdict } from "@/lib/verdict";
import { kickoffDate, kickoffTime, tzAbbrev } from "@/lib/datetime";
import { trackEvent } from "@/lib/analytics";
import { ProbabilityBar } from "./ProbabilityBar";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { Flag } from "./Flag";
import { FavoriteStar } from "./FavoriteStar";

/** The core dashboard card: matchup, predicted winner, W/D/L bar, score.
 *  When `tz` is given, kickoff time is shown in the user's local timezone.
 *  Set `showDate` when the card isn't inside a day-grouped list (e.g. the
 *  personalized country hub) so the local date is shown alongside the time. */
export function MatchCard({
  match,
  tz,
  showDate = false,
}: {
  match: MatchSummary;
  tz?: string;
  showDate?: boolean;
}) {
  const { teams, probabilities, predicted_score, confidence, predicted_winner } = match;
  const venue = [match.venue, match.venue_city].filter(Boolean).join(" · ");
  const live = match.status === "in_play";
  const finished = match.status === "finished";
  const hasScore = match.score_home != null && match.score_away != null;
  const verdict = predictionVerdict(match);

  return (
    <Link
      href={`/match/${match.match_id}`}
      onClick={() => trackEvent("match_card_click", { match_id: match.match_id })}
      className={`card-hover glass group block rounded-2xl p-4 focus:outline-none focus-visible:ring-2 focus-visible:ring-win/50 ${
        live ? "ring-1 ring-loss/40" : ""
      }`}
    >
      <div className="mb-3 flex items-center justify-between">
        <span className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
          {match.group ?? match.stage}
        </span>
        {live ? (
          <span
            className="inline-flex items-center gap-1.5 rounded-full bg-loss/15 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-loss"
            aria-label={`Live, ${liveLabel(match)}`}
          >
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-loss" aria-hidden />
            {liveLabel(match)}
          </span>
        ) : finished ? (
          <span className="rounded-full bg-surface-2/70 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-muted">
            FT
          </span>
        ) : (
          confidence && <ConfidenceBadge level={confidence} />
        )}
      </div>

      {!live && !finished && (match.kickoff_utc || venue) && (
        <div className="mb-3.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
          {match.kickoff_utc && tz && (
            <span className="inline-flex items-center gap-1.5 font-semibold text-win">
              <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" strokeLinecap="round" />
              </svg>
              {showDate
                ? `${kickoffDate(match.kickoff_utc, tz)} · ${kickoffTime(match.kickoff_utc, tz)}`
                : kickoffTime(match.kickoff_utc, tz)}
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
        <TeamRow name={teams.home} score={hasScore ? match.score_home : null} live={live || finished} />
        <TeamRow name={teams.away} score={hasScore ? match.score_away : null} live={live || finished} />
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

      <div className="mt-4 flex items-center justify-between gap-2 border-t border-border/60 pt-3 text-sm">
        {verdict ? (
          <span
            className={`inline-flex items-center gap-1 text-xs font-semibold ${
              verdict.kind === "miss" ? "text-loss" : "text-win"
            }`}
          >
            <span aria-hidden>{verdict.kind === "miss" ? "✗" : "✓"}</span>
            {verdict.label}
          </span>
        ) : (
          <span className="text-muted">
            Winner{" "}
            <strong className="font-semibold text-foreground">
              {predicted_winner ?? "—"}
            </strong>
          </span>
        )}
        {predicted_score && (
          <span className="chip rounded-md px-2 py-0.5 font-display text-sm font-bold tabular-nums text-foreground">
            {(live || finished) && (
              <span className="mr-1.5 align-middle text-[10px] font-semibold uppercase tracking-wide text-muted">
                Predicted
              </span>
            )}
            {formatScore(predicted_score.home, predicted_score.away)}
          </span>
        )}
      </div>
    </Link>
  );
}

function TeamRow({
  name,
  score,
  live,
}: {
  name: string;
  score?: number | null;
  live?: boolean;
}) {
  return (
    <div className="flex items-center gap-2.5">
      <Flag team={name} size={24} />
      <span className="min-w-0 flex-1 truncate font-display text-[15px] font-semibold tracking-tight">
        {name}
      </span>
      {live && score != null && (
        <span className="font-display text-lg font-extrabold tabular-nums">{score}</span>
      )}
      <FavoriteStar team={name} />
    </div>
  );
}
