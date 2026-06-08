import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getMatchServer } from "@/lib/api";
import { APP_NAME } from "@/lib/constants";
import { pct, formatScore } from "@/lib/format";
import { ProbabilityBar } from "@/components/ProbabilityBar";
import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { ReasonsList } from "@/components/ReasonsList";
import { FeatureImportanceChart } from "@/components/FeatureImportanceChart";
import { OddsCompare } from "@/components/OddsCompare";
import { Flag } from "@/components/Flag";
import { LocalKickoff } from "@/components/LocalKickoff";

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
  return { title, description, openGraph: { title, description } };
}

export default async function MatchDetailPage({ params }: { params: { id: string } }) {
  const p = await getMatchServer(params.id);
  if (!p) notFound();

  const { home, away } = p.teams;
  const venue = [p.venue, p.venue_city, p.venue_country].filter(Boolean).join(", ");

  return (
    <div className="fade-up mx-auto max-w-3xl space-y-6">
      <Link href="/matches" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-foreground">
        <span aria-hidden>←</span> All matches
      </Link>

      {/* Headline matchup (server-rendered) */}
      <section className="glass rounded-2xl p-6">
        <div className="mb-5 flex items-center justify-between">
          <span className="font-display text-xs font-semibold uppercase tracking-wider text-muted">
            World Cup 2026
          </span>
          <ConfidenceBadge level={p.confidence} />
        </div>

        <LocalKickoff iso={p.kickoff_utc} venue={venue || null} />

        <div className="grid grid-cols-[1fr_auto_1fr] items-start gap-2 sm:gap-3">
          <TeamHead name={home} prob={p.probabilities.home_win} />
          <div className="px-1 pt-3 text-center sm:px-2">
            <div className="font-display text-2xl font-extrabold tabular-nums sm:text-3xl">
              {formatScore(p.predicted_score.home, p.predicted_score.away)}
            </div>
            <div className="mt-1 text-[10px] uppercase tracking-wide text-muted sm:text-[11px]">
              predicted
            </div>
          </div>
          <TeamHead name={away} prob={p.probabilities.away_win} />
        </div>

        <div className="mt-6">
          <ProbabilityBar probabilities={p.probabilities} homeLabel={home} awayLabel={away} />
        </div>
        <p className="mt-4 text-center text-sm text-muted">
          Most likely scoreline{" "}
          <strong className="text-foreground">
            {home} {formatScore(p.predicted_score.home, p.predicted_score.away)} {away}
          </strong>{" "}
          · {pct(p.predicted_score.probability)} likely
        </p>
      </section>

      {/* Why (server-rendered reasons; chart hydrates client-side) */}
      <section className="glass rounded-2xl p-6">
        <h2 className="mb-4 font-display text-lg font-bold">Why this prediction</h2>
        <ReasonsList reasons={p.reasons} />
        {p.top_features.length > 0 && (
          <>
            <h3 className="mb-2 mt-6 text-xs font-semibold uppercase tracking-wider text-muted">
              Most important factors
            </h3>
            <FeatureImportanceChart features={p.top_features} />
          </>
        )}
      </section>

      <section className="glass rounded-2xl p-6">
        <h2 className="mb-3 font-display text-lg font-bold">Head-to-head</h2>
        {p.head_to_head.matches > 0 ? (
          <p className="text-sm text-foreground/90">
            Last {p.head_to_head.matches} meetings — {home}:{" "}
            <strong>{p.head_to_head.home_wins}W</strong>, {p.head_to_head.draws}D,{" "}
            {away}: <strong>{p.head_to_head.away_wins}W</strong>.
          </p>
        ) : (
          <p className="text-sm text-muted">No recent meetings on record.</p>
        )}
      </section>

      <section>
        <h2 className="mb-3 font-display text-lg font-bold">Odds comparison</h2>
        <OddsCompare available={p.odds_comparison.available} />
      </section>

      <p className="text-center text-xs text-muted/60">{p.disclaimer}</p>
    </div>
  );
}

function TeamHead({ name, prob }: { name: string; prob: number }) {
  return (
    <div className="flex min-w-0 flex-col items-center text-center">
      <Flag team={name} size={44} />
      <span className="mt-2 font-display text-sm font-bold leading-tight tracking-tight sm:text-lg">
        {name}
      </span>
      <span className="mt-1.5 font-display text-xl font-extrabold tabular-nums text-win sm:text-2xl">
        {pct(prob)}
      </span>
    </div>
  );
}
