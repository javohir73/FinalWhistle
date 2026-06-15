"use client";

import Link from "next/link";
import { getMatchSummary } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { pct, formatScore } from "@/lib/format";
import { liveLabel, penaltyTally, isLiveNow } from "@/lib/liveLabel";
import { predictionVerdict } from "@/lib/verdict";
import type { MatchSummary, PredictedScore, Probabilities } from "@/lib/types";
import { Flag } from "@/components/Flag";
import { ProbabilityBar } from "@/components/ProbabilityBar";

/** Match-page headline: the two teams around a center scoreboard.
 *
 *  Before kickoff the center shows the model's predicted score (as before).
 *  Once the match is live or finished it shows the ACTUAL score — with a LIVE
 *  minute or FULL TIME badge — and the prediction moves to the line below, so
 *  predicted and actual are always visible side by side. Polls the summary
 *  endpoint every 30s (same cadence as the matches board) until full time. */
export function MatchScoreboard({
  matchId,
  home,
  away,
  homeTeamId,
  awayTeamId,
  probabilities,
  predicted,
  initialSummary,
}: {
  matchId: number;
  home: string;
  away: string;
  homeTeamId?: number | null;
  awayTeamId?: number | null;
  probabilities: Probabilities;
  predicted: PredictedScore;
  initialSummary?: MatchSummary | null;
}) {
  const finishedAtRender = initialSummary?.status === "finished";
  const state = useFetch<MatchSummary>(
    () => getMatchSummary(matchId),
    [matchId],
    finishedAtRender ? undefined : 30_000,
    initialSummary ?? undefined,
  );
  const summary = state.status === "success" ? state.data : initialSummary ?? null;

  const live = !!summary && isLiveNow(summary);
  // Treat a match stuck `in_play` past the live window as over, so the detail
  // page doesn't show a ticking live clock hours after full time.
  const finished =
    summary?.status === "finished" || (summary?.status === "in_play" && !live);
  const hasActual =
    (live || finished) && summary != null &&
    summary.score_home != null && summary.score_away != null;
  const verdict = summary ? predictionVerdict(summary) : null;

  return (
    <>
      <div className="grid grid-cols-[1fr_auto_1fr] items-start gap-2 sm:gap-3">
        <TeamHead name={home} prob={probabilities.home_win} teamId={homeTeamId} />
        <div className="px-1 pt-3 text-center sm:px-2">
          <div className="font-display text-2xl font-extrabold tabular-nums sm:text-3xl">
            {hasActual
              ? formatScore(summary!.score_home, summary!.score_away)
              : formatScore(predicted.home, predicted.away)}
          </div>
          <div className="mt-1 text-[10px] uppercase tracking-wide sm:text-[11px]">
            {live ? (
              <span
                className="inline-flex items-center gap-1 font-bold text-loss"
                aria-label={`Live, ${liveLabel(summary!)}`}
              >
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-loss" aria-hidden />
                {liveLabel(summary!)}
              </span>
            ) : finished ? (
              <span className="font-bold text-muted">FT</span>
            ) : (
              <span className="text-muted">predicted</span>
            )}
          </div>
          {hasActual && penaltyTally(summary!) && (
            <div className="mt-0.5 text-[10px] tabular-nums text-muted sm:text-[11px]">
              ({penaltyTally(summary!)} pens)
            </div>
          )}
        </div>
        <TeamHead name={away} prob={probabilities.away_win} teamId={awayTeamId} />
      </div>

      <div className="mt-6">
        <ProbabilityBar probabilities={probabilities} homeLabel={home} awayLabel={away} />
      </div>

      <p className="mt-4 text-center text-sm text-muted">
        {hasActual ? "Model predicted" : "Most likely scoreline"}{" "}
        <strong className="text-foreground">
          {home} {formatScore(predicted.home, predicted.away)} {away}
        </strong>{" "}
        · {pct(predicted.probability)} likely
      </p>

      {verdict && (
        <p className="mt-2 text-center">
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${
              verdict.kind === "exact"
                ? "bg-win/15 text-win ring-1 ring-win/30"
                : verdict.kind === "winner"
                  ? "bg-win/10 text-win"
                  : "bg-loss/10 text-loss"
            }`}
          >
            <span aria-hidden>{verdict.kind === "miss" ? "✗" : "✓"}</span>
            {verdict.label}
          </span>
        </p>
      )}
    </>
  );
}

function TeamHead({ name, prob, teamId }: { name: string; prob: number; teamId?: number | null }) {
  const inner = (
    <>
      <Flag team={name} size={44} />
      <span className="mt-2 font-display text-sm font-bold leading-tight tracking-tight sm:text-lg">
        {name}
      </span>
    </>
  );
  return (
    <div className="flex min-w-0 flex-col items-center text-center">
      {teamId ? (
        <Link
          href={`/team/${teamId}`}
          className="flex flex-col items-center rounded-lg transition hover:text-win focus:outline-none focus-visible:ring-2 focus-visible:ring-win/50"
        >
          {inner}
        </Link>
      ) : (
        <div className="flex flex-col items-center">{inner}</div>
      )}
      <span className="mt-1.5 font-display text-xl font-extrabold tabular-nums text-win sm:text-2xl">
        {pct(prob)}
      </span>
    </div>
  );
}
