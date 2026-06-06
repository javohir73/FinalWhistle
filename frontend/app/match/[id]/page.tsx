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
import { Loading, ErrorState } from "@/components/States";

export default function MatchDetailPage({ params }: { params: { id: string } }) {
  const { id } = params;
  const state = useFetch(() => getMatch(id), [id]);

  if (state.status === "loading") return <Loading label="Loading match…" />;
  if (state.status === "error") return <ErrorState message={state.message} />;

  const p = state.data;
  const { home, away } = p.teams;

  return (
    <div className="space-y-6">
      <Link href="/" className="text-sm text-foreground/60 hover:underline">
        ← All matches
      </Link>

      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">
          {home} vs {away}
        </h1>
        <ConfidenceBadge level={p.confidence} />
      </div>

      <section className="rounded-xl border border-border p-5">
        <div className="mb-4 grid grid-cols-3 text-center">
          <Stat label={`${home} win`} value={pct(p.probabilities.home_win)} />
          <Stat label="Draw" value={pct(p.probabilities.draw)} />
          <Stat label={`${away} win`} value={pct(p.probabilities.away_win)} />
        </div>
        <ProbabilityBar probabilities={p.probabilities} homeLabel={home} awayLabel={away} />
        <p className="mt-4 text-sm text-foreground/60">
          Predicted score:{" "}
          <strong className="text-foreground">
            {home} {formatScore(p.predicted_score.home, p.predicted_score.away)} {away}
          </strong>{" "}
          ({pct(p.predicted_score.probability)} likely)
        </p>
      </section>

      <section className="rounded-xl border border-border p-5">
        <h2 className="mb-3 font-semibold">Why this prediction</h2>
        <ReasonsList reasons={p.reasons} />
        {p.top_features.length > 0 && (
          <>
            <h3 className="mb-1 mt-5 text-sm font-medium text-foreground/70">
              Most important factors
            </h3>
            <FeatureImportanceChart features={p.top_features} />
          </>
        )}
      </section>

      <section className="rounded-xl border border-border p-5">
        <h2 className="mb-3 font-semibold">Head-to-head (recent)</h2>
        {p.head_to_head.matches > 0 ? (
          <p className="text-sm text-foreground/70">
            Last {p.head_to_head.matches} meetings — {home}: {p.head_to_head.home_wins}W,{" "}
            {p.head_to_head.draws}D, {away}: {p.head_to_head.away_wins}W.
          </p>
        ) : (
          <p className="text-sm text-foreground/50">No recent meetings on record.</p>
        )}
      </section>

      <section>
        <h2 className="mb-3 font-semibold">Odds comparison</h2>
        <OddsCompare available={p.odds_comparison.available} />
      </section>

      <p className="text-xs text-foreground/40">{p.disclaimer}</p>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-2xl font-bold tabular-nums">{value}</div>
      <div className="text-xs text-foreground/60">{label}</div>
    </div>
  );
}
