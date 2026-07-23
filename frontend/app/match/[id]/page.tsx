import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getMatchServer,
  getMatchSummaryServer,
  getMatchGoalscorersServer,
  getModelRecordServer,
} from "@/lib/api";
import { getTournament } from "@/lib/tournament";
import { APP_NAME } from "@/lib/constants";
import { pct, formatScore, topOutcome } from "@/lib/format";
import { prematchCall } from "@/lib/verdict";
import { ReasonsList } from "@/components/ReasonsList";
import { FeatureImportanceChart } from "@/components/FeatureImportanceChart";
import { MatchScoreboard } from "@/components/MatchScoreboard";
import { MatchLineups } from "@/components/MatchLineups";
import { MatchTabs } from "@/components/MatchTabs";
import { ModelVsMarket } from "@/components/ModelVsMarket";
import { MatchUserPrediction } from "@/components/MatchUserPrediction";
import { LocalKickoff } from "@/components/LocalKickoff";
import { ShareButton } from "@/components/ShareButton";
import { Flag } from "@/components/Flag";
import { GoalMarkets } from "@/components/GoalMarkets";
import { LikelyScorers } from "@/components/LikelyScorers";
import { AvailabilityNote } from "@/components/AvailabilityNote";
import { MatchWriteup } from "@/components/MatchWriteup";
import type { MatchSummary } from "@/lib/types";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  const p = await getMatchServer(id);
  if (!p) return { title: `Match — ${APP_NAME}` };
  const title = `${p.teams.home} vs ${p.teams.away} — prediction | ${APP_NAME}`;
  const description = `ML model prediction for ${p.teams.home} vs ${p.teams.away}: ${p.teams.home} ${pct(
    p.probabilities.home_win,
  )}, draw ${pct(p.probabilities.draw)}, ${p.teams.away} ${pct(
    p.probabilities.away_win,
  )}. Most likely score ${formatScore(p.predicted_score.home, p.predicted_score.away)}.`;
  return {
    title, description,
    alternates: { canonical: `/match/${id}` },
    openGraph: { title, description },
  };
}

export default async function MatchDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const p = await getMatchServer(id);
  // Seeds the scoreboard with the actual status/score; the page must still
  // render (prediction-only) if this secondary fetch hiccups.
  const summary = await getMatchSummaryServer(id).catch(() => null);
  const tournament = await getTournament();
  // A just-drawn knockout tie exists (summary is served) before its prediction is
  // generated. Show the matchup + a "prediction on the way" note rather than a
  // hard 404; only 404 when the match genuinely doesn't exist.
  if (!p) {
    if (!summary) notFound();
    return <PredictionPending summary={summary} tournamentName={tournament.name} />;
  }
  const record = await getModelRecordServer().catch(() => null);
  // Likely scorers (squad estimate or confirmed XI); null until player data
  // exists for a team. A hiccup here must not take down the page.
  const goalscorers = await getMatchGoalscorersServer(id).catch(() => null);

  const { home, away } = p.teams;
  const venue = [p.venue, p.venue_city, p.venue_country].filter(Boolean).join(", ");
  const call = prematchCall(p.probabilities, p.teams);
  // The model's favoured side (for the "Why {winner}?" heading and the AI's-call
  // headline); a draw lean has no single side, so fall back to the generic
  // heading / "Too close to call" sentence.
  const topSide = topOutcome(p.probabilities);
  const predictedWinner = topSide === "home" ? home : topSide === "away" ? away : null;

  return (
    <div className="fade-up mx-auto max-w-2xl space-y-6">
      <div className="flex items-center justify-between gap-3">
        <Link href="/matches" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-foreground">
          <span aria-hidden>←</span> All matches
        </Link>
        {p.group && (
          <span className="font-display text-[13px] font-semibold text-muted">{p.group}</span>
        )}
        <ShareButton title={`${home} vs ${away} — ${tournament.name} prediction`} />
      </div>

      <LocalKickoff iso={p.kickoff_utc} venue={venue || null} />

      {/* Bare matchup + the AI's call card (the scoreboard hydrates and promotes
          the actual score once a match is live or final). */}
      <MatchScoreboard
        matchId={p.match_id}
        home={home}
        away={away}
        homeTeamId={p.home_team_id}
        awayTeamId={p.away_team_id}
        probabilities={p.probabilities}
        predicted={p.predicted_score}
        initialSummary={summary}
        confidence={p.confidence}
        predictedWinner={predictedWinner}
        caveat={call?.label ?? null}
        knockout={p.knockout ?? null}
      />

      {/* Tabbed detail: Overview (the AI's reasoning + your pick) and Lineups.
          Lineups are lazily fetched only when that tab is opened. */}
      <MatchTabs
        overview={
          <div className="space-y-6">
            {/* The breakdown — Fable-style narrative writeup (pipeline-generated,
                deterministic; hidden for pre-feature predictions). */}
            <MatchWriteup home={home} away={away} writeup={p.writeup} />

            {/* Why (server-rendered reasons; chart hydrates client-side) */}
            <section className="glass rounded-2xl p-6">
              <h2 className="mb-4 font-display text-lg font-bold text-foreground">
                {predictedWinner ? `Why ${predictedWinner}?` : "Why this prediction"}
              </h2>
              <ReasonsList reasons={p.reasons} />
              {p.top_features.length > 0 && (
                <>
                  <h3 className="mb-2 mt-6 text-xs font-semibold uppercase tracking-wider text-muted">
                    What drove this prediction
                  </h3>
                  <FeatureImportanceChart features={p.top_features} />
                </>
              )}
            </section>

            {/* Model vs market — W/D/L against the bookmaker consensus (hidden
                until an odds snapshot exists for this match). */}
            <ModelVsMarket prediction={p} home={home} away={away} />

            {/* Goals — per-team bands, over/under and BTTS (hidden until predicted). */}
            {p.goal_markets && (
              <GoalMarkets home={home} away={away} markets={p.goal_markets} />
            )}

            {/* Likely scorers — top players per team (hidden until player data). */}
            {goalscorers && (
              <LikelyScorers home={home} away={away} data={goalscorers} />
            )}

            {/* Availability — announced-XI context (experimental; not in the number). */}
            <AvailabilityNote availability={p.availability} />

            {/* Your prediction — segmented W/D/L pick vs the AI (anonymous, local).
                Needs the live match summary; rendered only when it's available. */}
            {summary && (
              <section>
                <h2 className="mb-3 font-display text-lg font-bold">Your prediction</h2>
                <MatchUserPrediction match={summary} />
              </section>
            )}
          </div>
        }
        lineups={<MatchLineups matchId={p.match_id} />}
      />

      <p className="text-center text-xs leading-relaxed text-muted">
        {(() => {
          // Prefer record.last_updated when it's non-null and newer than
          // p.generated_at. Compare numerically — the two timestamps come from
          // different serializers (naive vs offset ISO), so string comparison
          // mis-orders them.
          const epoch = (ts: string | null | undefined): number => {
            if (!ts) return NaN;
            return Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(ts) ? ts : ts + "Z");
          };
          const base = p.generated_at;
          const recordTs = record?.last_updated ?? null;
          let displayTs: string | null = base;
          if (recordTs && (!base || epoch(recordTs) > epoch(base))) {
            displayTs = recordTs;
          }
          return displayTs ? <>Model updated {fmtUpdated(displayTs)} · </> : null;
        })()}
        {p.disclaimer}
      </p>
    </div>
  );
}

/** Shown when a match exists but its AI prediction hasn't been generated yet
 *  (e.g. a knockout tie just drawn, before the next pipeline run). Renders the
 *  matchup, any live/final score, and lineups — never a 404. */
function PredictionPending({
  summary,
  tournamentName,
}: {
  summary: MatchSummary;
  tournamentName: string;
}) {
  const { home, away } = summary.teams;
  const venue = [summary.venue, summary.venue_city, summary.venue_country]
    .filter(Boolean)
    .join(", ");
  const live = summary.status === "in_play";
  const finished = summary.status === "finished";
  const showScore =
    (live || finished) && summary.score_home != null && summary.score_away != null;

  return (
    <div className="fade-up mx-auto max-w-2xl space-y-6">
      <div className="flex items-center justify-between gap-3">
        <Link href="/matches" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-foreground">
          <span aria-hidden>←</span> All matches
        </Link>
        {summary.group && (
          <span className="font-display text-[13px] font-semibold text-muted">{summary.group}</span>
        )}
        <ShareButton title={`${home} vs ${away} — ${tournamentName}`} />
      </div>

      <LocalKickoff iso={summary.kickoff_utc} venue={venue || null} />

      {/* Bare matchup + live/final score (the AI's-call card appears once predicted). */}
      <section className="glass rounded-2xl p-6">
        <div className="flex items-center justify-center gap-5">
          <div className="flex flex-col items-center gap-2 text-center">
            <Flag team={home} size={48} />
            <span className="font-display text-sm font-bold">{home}</span>
          </div>
          <span className="font-display text-2xl font-extrabold tabular-nums text-muted">
            {showScore ? `${summary.score_home}–${summary.score_away}` : "vs"}
          </span>
          <div className="flex flex-col items-center gap-2 text-center">
            <Flag team={away} size={48} />
            <span className="font-display text-sm font-bold">{away}</span>
          </div>
        </div>
        {live && (
          <p className="mt-3 text-center text-xs font-semibold uppercase tracking-wide text-loss">
            Live{summary.minute != null ? ` · ${summary.minute}'` : ""}
          </p>
        )}
      </section>

      {/* Prediction-pending note */}
      <section className="glass rounded-2xl p-6 text-center">
        <h2 className="font-display text-base font-bold text-foreground">ML model prediction on the way</h2>
        <p className="mx-auto mt-1.5 max-w-md text-sm leading-relaxed text-muted">
          The model generates this match&apos;s prediction shortly after both teams are
          confirmed. Check back soon for the full breakdown.
        </p>
      </section>

      {/* Lineups load independently of the prediction. */}
      <MatchLineups matchId={summary.match_id} />
    </div>
  );
}

function fmtUpdated(iso: string): string {
  // Backend timestamps are UTC but may be naive (no offset) — tag as UTC so the
  // date doesn't shift a day in negative-offset interpretations.
  const utc = /[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`;
  try {
    return new Intl.DateTimeFormat("en-GB", {
      day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
    }).format(new Date(utc));
  } catch {
    return iso.slice(0, 10);
  }
}
