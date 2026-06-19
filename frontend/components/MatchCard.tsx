"use client";

import Link from "next/link";
import type { MatchSummary } from "@/lib/types";
import { formatScore } from "@/lib/format";
import { liveLabel, isLiveNow } from "@/lib/liveLabel";
import { predictionVerdict, prematchCall } from "@/lib/verdict";
import { kickoffDate, kickoffTime } from "@/lib/datetime";
import { trackEvent } from "@/lib/analytics";
import { ProbabilityBar } from "./ProbabilityBar";
import { Flag } from "./Flag";
import { FavoriteStar } from "./FavoriteStar";

/** The core dashboard card: matchup, predicted winner, W/D/L bar, score.
 *  The status pill (top-right) carries the time/state: an amber kickoff-time
 *  pill before kickoff, a rose live-minute pill in play, a muted "Full time"
 *  pill once over. When `tz` is given the kickoff time is shown in the user's
 *  local timezone. Set `showDate` when the card isn't inside a day-grouped list
 *  (e.g. the personalized country hub) so the local date leads the time pill. */
export function MatchCard({
  match,
  tz,
  showDate = false,
}: {
  match: MatchSummary;
  tz?: string;
  showDate?: boolean;
}) {
  const { teams, probabilities, predicted_score, predicted_winner } = match;
  const live = isLiveNow(match);
  // A match the feed left stuck `in_play` past the live window is treated as
  // over (show its last score as a result) rather than perpetually "live".
  const finished = match.status === "finished" || (match.status === "in_play" && !live);
  const hasScore = match.score_home != null && match.score_away != null;
  const verdict = predictionVerdict(match);
  const call = prematchCall(probabilities, teams);
  const kickoffPill =
    match.kickoff_utc && tz
      ? showDate
        ? `${kickoffDate(match.kickoff_utc, tz)} · ${kickoffTime(match.kickoff_utc, tz)}`
        : kickoffTime(match.kickoff_utc, tz)
      : null;

  return (
    <Link
      href={`/match/${match.match_id}`}
      onClick={() => trackEvent("match_card_click", { match_id: match.match_id })}
      className={`card-hover glass group block rounded-2xl p-4 ${
        live ? "ring-1 ring-loss/40" : ""
      }`}
    >
      <div className="mb-3 flex items-center justify-between gap-2">
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
            Full time
          </span>
        ) : (
          kickoffPill && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-draw/15 px-2 py-0.5 text-[11px] font-bold tabular-nums text-[#9a730f]">
              <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" strokeLinecap="round" />
              </svg>
              {kickoffPill}
            </span>
          )
        )}
      </div>

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

      <div className="mt-4 flex items-center justify-between gap-2 border-t border-border pt-3 text-sm">
        {finished && verdict ? (
          <span
            className={`inline-flex items-center gap-1.5 text-xs font-semibold ${
              verdict.kind === "miss" ? "text-loss" : "text-lime-deep"
            }`}
          >
            <span aria-hidden>{verdict.kind === "miss" ? "✕" : "✓"}</span>
            {verdict.kind === "miss"
              ? "Upset — we missed it"
              : verdict.kind === "exact"
                ? "Exact score!"
                : "Called it"}
          </span>
        ) : call ? (
          <span
            className={`text-xs font-semibold ${
              call.tone === "draw" ? "text-draw" : "text-lime-deep"
            }`}
          >
            {call.label}
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
          <span className="inline-flex items-center rounded-md bg-surface-2 px-2 py-0.5 font-display text-sm font-bold tabular-nums text-foreground">
            <span className="mr-1.5 align-middle text-[10px] font-semibold uppercase tracking-wide text-muted">
              AI
            </span>
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
