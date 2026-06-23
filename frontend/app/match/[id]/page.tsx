import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getMatchServer, getMatchSummaryServer, getModelRecordServer } from "@/lib/api";
import { APP_NAME } from "@/lib/constants";
import { pct, formatScore, topOutcome } from "@/lib/format";
import { prematchCall } from "@/lib/verdict";
import { ReasonsList } from "@/components/ReasonsList";
import { FeatureImportanceChart } from "@/components/FeatureImportanceChart";
import { MatchScoreboard } from "@/components/MatchScoreboard";
import { MatchLineups } from "@/components/MatchLineups";
import { MatchUserPrediction } from "@/components/MatchUserPrediction";
import { LocalKickoff } from "@/components/LocalKickoff";
import { ShareButton } from "@/components/ShareButton";

export async function generateMetadata({
  params,
}: {
  params: { id: string };
}): Promise<Metadata> {
  const p = await getMatchServer(params.id);
  if (!p) return { title: `Match — ${APP_NAME}` };
  const title = `${p.teams.home} vs ${p.teams.away} — prediction | ${APP_NAME}`;
  const description = `AI prediction for ${p.teams.home} vs ${p.teams.away}: ${p.teams.home} ${pct(
    p.probabilities.home_win,
  )}, draw ${pct(p.probabilities.draw)}, ${p.teams.away} ${pct(
    p.probabilities.away_win,
  )}. Most likely score ${formatScore(p.predicted_score.home, p.predicted_score.away)}.`;
  return {
    title, description,
    alternates: { canonical: `/match/${params.id}` },
    openGraph: { title, description },
  };
}

export default async function MatchDetailPage({ params }: { params: { id: string } }) {
  const p = await getMatchServer(params.id);
  if (!p) notFound();
  // Seeds the scoreboard with the actual status/score; the page must still
  // render (prediction-only) if this secondary fetch hiccups.
  const summary = await getMatchSummaryServer(params.id).catch(() => null);
  const record = await getModelRecordServer().catch(() => null);

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
        <ShareButton title={`${home} vs ${away} — World Cup 2026 prediction`} />
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
      />

      {/* Lineups — official starting XI + bench, lazily fetched client-side.
          Display-only; degrades to a placeholder when none are announced yet. */}
      <section>
        <h2 className="mb-3 font-display text-lg font-bold">Lineups</h2>
        <MatchLineups matchId={p.match_id} />
      </section>

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

      {/* Your prediction — segmented W/D/L pick vs the AI (anonymous, local).
          Needs the live match summary; rendered only when it's available. */}
      {summary && (
        <section>
          <h2 className="mb-3 font-display text-lg font-bold">Your prediction</h2>
          <MatchUserPrediction match={summary} />
        </section>
      )}

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
