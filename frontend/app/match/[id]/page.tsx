"use client";

import Link from "next/link";
import { getMatch } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { pct, formatScore } from "@/lib/format";
import { ProbabilityBar } from "@/components/ProbabilityBar";
import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { ReasonsList } from "@/components/ReasonsList";
import { FeatureImportanceChart } from "@/components/FeatureImportanceChart";
import { OddsCompare } from "@/components/OddsCompare";
import { Flag } from "@/components/Flag";
import { Loading, ErrorState } from "@/components/States";

export default function MatchDetailPage({ params }: { params: { id: string } }) {
  const { id } = params;
  const state = useFetch(() => getMatch(id), [id]);

  if (state.status === "loading") return <Loading label="Loading match…" />;
  if (state.status === "error") return <ErrorState message={state.message} />;

  const p = state.data;
  const { home, away } = p.teams;

  return (
    <div className="fade-up mx-auto max-w-3xl space-y-6">
      <Link href="/" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-foreground">
        <span aria-hidden>←</span> All matches
      </Link>

      {/* Headline matchup */}
      <section className="glass rounded-2xl p-6">
        <div className="mb-5 flex items-center justify-between">
          <span className="font-display text-xs font-semibold uppercase tracking-wider text-muted">
            World Cup 2026
          </span>
          <ConfidenceBadge level={p.confidence} />
        </div>

        <div className="grid grid-cols-3 items-center gap-2">
          <TeamHead name={home} prob={p.probabilities.home_win} side="left" />
          <div className="text-center">
            <div className="font-display text-3xl font-extrabold tabular-nums">
              {formatScore(p.predicted_score.home, p.predicted_score.away)}
            </div>
            <div className="mt-1 text-[11px] uppercase tracking-wide text-muted">
              predicted
            </div>
          </div>
          <TeamHead name={away} prob={p.probabilities.away_win} side="right" />
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

      {/* Why */}
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

      {/* H2H */}
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

function TeamHead({
  name,
  prob,
  side,
}: {
  name: string;
  prob: number;
  side: "left" | "right";
}) {
  return (
    <div className={side === "right" ? "text-right" : "text-left"}>
      <div className={`flex items-center gap-2.5 ${side === "right" ? "flex-row-reverse" : ""}`}>
        <Flag team={name} size={40} />
        <span className="font-display text-lg font-bold leading-tight tracking-tight">
          {name}
        </span>
      </div>
      <div className="mt-2 font-display text-2xl font-extrabold tabular-nums text-win">
        {pct(prob)}
      </div>
    </div>
  );
}
