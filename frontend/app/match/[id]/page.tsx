"use client";

import Link from "next/link";
import { getMatch } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { useTimezone } from "@/lib/useTimezone";
import { dayHeading, kickoffTime, tzAbbrev } from "@/lib/datetime";
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
  const { tz } = useTimezone();

  if (state.status === "loading") return <Loading label="Loading match…" />;
  if (state.status === "error") return <ErrorState message={state.message} />;

  const p = state.data;
  const { home, away } = p.teams;
  const venue = [p.venue, p.venue_city, p.venue_country].filter(Boolean).join(", ");

  return (
    <div className="fade-up mx-auto max-w-3xl space-y-6">
      <Link href="/matches" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-foreground">
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

        {(p.kickoff_utc || venue) && (
          <div className="mb-5 flex flex-wrap items-center justify-center gap-x-4 gap-y-1.5 text-sm text-muted">
            {p.kickoff_utc && (
              <span className="inline-flex items-center gap-1.5 font-semibold text-foreground">
                <svg viewBox="0 0 24 24" className="h-4 w-4 text-win" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" strokeLinecap="round" />
                </svg>
                {dayHeading(p.kickoff_utc, tz)} · {kickoffTime(p.kickoff_utc, tz)}{" "}
                <span className="font-medium text-muted">{tzAbbrev(p.kickoff_utc, tz)}</span>
              </span>
            )}
            {venue && (
              <span className="inline-flex items-center gap-1.5">
                <svg viewBox="0 0 24 24" className="h-4 w-4 text-win" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 21s-7-5.2-7-11a7 7 0 1 1 14 0c0 5.8-7 11-7 11Z" strokeLinejoin="round" />
                  <circle cx="12" cy="10" r="2.5" />
                </svg>
                {venue}
              </span>
            )}
          </div>
        )}

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
