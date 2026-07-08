"use client";

import Link from "next/link";
import { getMatchSummary } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { pct, formatScore } from "@/lib/format";
import { liveLabel, penaltyTally, isLiveNow } from "@/lib/liveLabel";
import { predictionVerdict } from "@/lib/verdict";
import { ShootoutNote, BasisTag, KnockoutDrawNote } from "@/components/ShootoutNote";
import { KnockoutAdvanceCard } from "@/components/KnockoutAdvanceCard";
import type { KnockoutAdvance, MatchSummary, PredictedScore, Probabilities, GoalEvent, CardEvent } from "@/lib/types";
import { Flag } from "@/components/Flag";
import { ProbabilityBar } from "@/components/ProbabilityBar";
import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { FavoriteStar } from "@/components/FavoriteStar";

/** Match-page headline, prototype "Match" layout: a bare matchup (flags + names
 *  + "vs") on the canvas, then a distinct "The AI's call" card holding the plain
 *  verdict, the caveat, the confidence pill and the W/D/L bar.
 *
 *  Once a match is live or finished the centre of the matchup shows the ACTUAL
 *  score with a LIVE minute / FULL TIME badge, the bar switches to the in-play
 *  win probability, and the card keeps the model's pre-match call visible. Polls
 *  the summary endpoint every 30s until full time. */
export function MatchScoreboard({
  matchId,
  home,
  away,
  homeTeamId,
  awayTeamId,
  probabilities,
  predicted,
  initialSummary,
  confidence,
  predictedWinner,
  caveat,
  knockout,
}: {
  matchId: number;
  home: string;
  away: string;
  homeTeamId?: number | null;
  awayTeamId?: number | null;
  probabilities: Probabilities;
  predicted: PredictedScore;
  initialSummary?: MatchSummary | null;
  confidence?: string | null;
  /** The model's favoured side as a display name, or null on a draw lean. */
  predictedWinner?: string | null;
  /** One-line plain-language caveat (e.g. "Too close to call"). */
  caveat?: string | null;
  /** Knockout resolution block (v0.5) — who goes through, past the 90th minute. */
  knockout?: KnockoutAdvance | null;
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

  // While the match is live, the win % and the bar reflect the in-play
  // probability (current score + time left); otherwise they show the pre-match
  // model. The pre-match "Model predicted X-Y" note stays below either way.
  const liveProbs = live ? summary?.live_probabilities ?? null : null;
  const shownProbs = liveProbs ?? probabilities;
  const predictedScore = formatScore(predicted.home, predicted.away);
  // The headline says "X to win" only with a decisive predicted scoreline; a
  // level modal scoreline falls back to "Too close to call".
  const showsWinner = !!predictedWinner && predicted.home !== predicted.away;

  return (
    <>
      {/* ===== Bare matchup ===== */}
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 sm:gap-3">
        <TeamHead name={home} teamId={homeTeamId} />
        <div className="px-1 text-center sm:px-2">
          {hasActual ? (
            <>
              <div className="font-display text-3xl font-extrabold tabular-nums sm:text-4xl">
                {formatScore(summary!.score_home, summary!.score_away)}
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
                ) : (
                  <span className="font-bold text-muted">FT</span>
                )}
              </div>
              {penaltyTally(summary!) && (
                <div className="mt-0.5 text-[10px] tabular-nums text-muted sm:text-[11px]">
                  ({penaltyTally(summary!)} pens)
                </div>
              )}
            </>
          ) : (
            <span className="font-display text-lg font-bold text-muted sm:text-xl">vs</span>
          )}
        </div>
        <TeamHead name={away} teamId={awayTeamId} />
      </div>

      {hasActual &&
        (timelineFor(summary!, "home").length > 0 ||
          timelineFor(summary!, "away").length > 0 ||
          yellowCount(summary!, "home") > 0 ||
          yellowCount(summary!, "away") > 0) && (
        <div className="mt-3 grid grid-cols-2 gap-x-4 text-[11px] text-muted sm:text-xs">
          <ul className="space-y-0.5 text-right">
            {timelineFor(summary!, "home").map((label, i) => (
              <li key={`h-${i}`} className="tabular-nums">{label}</li>
            ))}
            {yellowCount(summary!, "home") > 0 && (
              <li className="tabular-nums" aria-label="home yellow cards">
                🟨 ×{yellowCount(summary!, "home")}
              </li>
            )}
          </ul>
          <ul className="space-y-0.5 text-left">
            {timelineFor(summary!, "away").map((label, i) => (
              <li key={`a-${i}`} className="tabular-nums">{label}</li>
            ))}
            {yellowCount(summary!, "away") > 0 && (
              <li className="tabular-nums" aria-label="away yellow cards">
                🟨 ×{yellowCount(summary!, "away")}
              </li>
            )}
          </ul>
        </div>
      )}

      {/* ===== The AI's call ===== */}
      <section className="glass mt-5 rounded-2xl p-6 text-center">
        <span className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
          The AI&apos;s call
        </span>
        <p className="mt-2 font-display text-2xl font-extrabold tracking-tight text-foreground sm:text-[25px]">
          {/* Only say "X to win" when the most-likely scoreline actually has a
              winner. The favoured outcome (argmax W/D/L) can lean to a side while
              the modal scoreline is level — "{team} to win 1–1" reads as a
              contradiction, so a level scoreline falls back to "Too close to call"
              (the lean still shows in the bar below). */}
          {showsWinner ? (
            <>
              {predictedWinner} to win{" "}
              <span className="text-lime-deep">{predictedScore}</span>
            </>
          ) : (
            "Too close to call"
          )}
        </p>
        {/* Suppress the caveat when it would just repeat the "Too close to call"
            headline; keep it when it adds a lean (e.g. "{team} edge it"). */}
        {caveat && !(!showsWinner && caveat === "Too close to call") && (
          <p className="mt-1.5 text-sm text-muted">{caveat}</p>
        )}
        {confidence && (
          <div className="mt-4 flex justify-center">
            <ConfidenceBadge level={confidence} />
          </div>
        )}

        <div className="mt-5">
          {liveProbs && (
            <div className="mb-2 flex items-center justify-center gap-1.5 text-[10px] font-bold uppercase tracking-wide text-loss sm:text-[11px]">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-loss" aria-hidden />
              Live win probability
            </div>
          )}
          <ProbabilityBar probabilities={shownProbs} homeLabel={home} awayLabel={away} />
        </div>

        <p className="mt-4 text-sm text-muted">
          {hasActual ? "Model predicted" : "Most likely scoreline"}{" "}
          <strong className="text-foreground">
            {home} {predictedScore} {away}
          </strong>{" "}
          · {pct(predicted.probability)} likely
        </p>

        {/* Until full time a knockout tie needs resolving past the 90th minute:
            the v0.5 advance block when the prediction carries it, else the plain
            draw qualifier (legacy rows). Once finished the verdict's BasisTag +
            ShootoutNote take over. */}
        {!finished && knockout && (
          <KnockoutAdvanceCard knockout={knockout} home={home} away={away} />
        )}
        {!finished && !knockout && <KnockoutDrawNote stage={summary?.stage} />}

        {verdict && (
          <p className="mt-3">
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${
                verdict.kind === "miss" ? "bg-loss/15 text-loss" : "bg-win/15 text-lime-deep"
              }`}
            >
              <span aria-hidden>{verdict.kind === "miss" ? "✕" : "✓"}</span>
              {verdict.label}
              <BasisTag verdict={verdict} />
            </span>
          </p>
        )}
        {verdict && <ShootoutNote verdict={verdict} />}
      </section>
    </>
  );
}

function TeamHead({ name, teamId }: { name: string; teamId?: number | null }) {
  const inner = (
    <>
      <Flag team={name} size={60} />
      <span className="mt-2.5 font-display text-base font-extrabold leading-tight tracking-tight sm:text-lg">
        {name}
      </span>
    </>
  );
  return (
    <div className="flex min-w-0 flex-col items-center text-center">
      {teamId ? (
        <Link
          href={`/team/${teamId}`}
          className="flex flex-col items-center rounded-lg transition hover:text-lime-deep"
        >
          {inner}
        </Link>
      ) : (
        <div className="flex flex-col items-center">{inner}</div>
      )}
      <FavoriteStar team={name} size={18} className="mt-1.5" />
    </div>
  );
}

function formatScorer(g: GoalEvent): string {
  const annot = g.type === "penalty" ? " (pen)" : g.type === "own_goal" ? " (OG)" : "";
  const min = g.minute != null ? ` ${g.minute}'` : "";
  return `${g.player}${min}${annot}`;
}

/** Goals and red cards for one side, merged into one minute-ordered timeline.
 *  Yellows stay out of the timeline (rendered as a compact count instead). */
function timelineFor(s: MatchSummary, side: "home" | "away"): string[] {
  const goals = s.goal_events
    .filter((g) => g.side === side)
    .map((g) => ({ minute: g.minute, label: formatScorer(g) }));
  const reds = (s.card_events ?? [])
    .filter((c) => c.side === side && c.type === "red")
    .map((c) => ({ minute: c.minute, label: formatRedCard(c) }));
  return [...goals, ...reds]
    .sort((x, y) => (x.minute ?? 0) - (y.minute ?? 0))
    .map((e) => e.label);
}

function formatRedCard(c: CardEvent): string {
  const min = c.minute != null ? ` ${c.minute}'` : "";
  return `🟥 ${c.player}${min}`;
}

function yellowCount(s: MatchSummary, side: "home" | "away"): number {
  return (s.card_events ?? []).filter((c) => c.side === side && c.type === "yellow").length;
}
