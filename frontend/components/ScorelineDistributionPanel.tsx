import type { Probabilities, ScorelineDistribution, ScorelineOutcome } from "@/lib/types";
import { formatScore, pct, topOutcome } from "@/lib/format";

const OUTCOME_LABELS: Record<ScorelineOutcome, string> = {
  home: "Home win",
  draw: "Draw",
  away: "Away win",
};

export function ScorelineDistributionPanel({
  distribution,
  probabilities,
  home,
  away,
}: {
  distribution: ScorelineDistribution;
  probabilities: Probabilities;
  home: string;
  away: string;
}) {
  const headline = topOutcome(probabilities);
  const outcomeOrder: ScorelineOutcome[] = ["home", "draw", "away"];

  return (
    <section className="glass rounded-2xl p-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-display text-lg font-bold">Scoreline distribution</h2>
          <p className="mt-1 text-sm text-muted">
            xG {home} {distribution.expected_goals.home.toFixed(2)} · {away}{" "}
            {distribution.expected_goals.away.toFixed(2)}
          </p>
        </div>
        <div className="rounded-xl border border-border/70 bg-surface-2/60 px-3 py-2 text-right">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">
            Headline result
          </div>
          <div className="font-display text-sm font-bold text-win">
            {OUTCOME_LABELS[headline]}
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        {outcomeOrder.map((outcome) => {
          const scorelines = distribution.by_outcome[outcome] ?? [];
          const isHeadline = outcome === headline;

          return (
            <div
              key={outcome}
              className={`rounded-xl border p-3 ${
                isHeadline
                  ? "border-win/40 bg-win/10"
                  : "border-border/70 bg-surface-2/45"
              }`}
            >
              <div className="mb-3 flex items-center justify-between gap-2">
                <h3 className="font-display text-sm font-bold">
                  {OUTCOME_LABELS[outcome]}
                </h3>
                {isHeadline && (
                  <span className="rounded-full bg-win/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-win">
                    Pick
                  </span>
                )}
              </div>

              <ol className="space-y-2">
                {scorelines.map((line) => (
                  <li
                    key={`${outcome}-${line.home}-${line.away}`}
                    className="grid grid-cols-[3.5rem_1fr_2.5rem] items-center gap-2 text-sm"
                  >
                    <span className="font-display font-bold tabular-nums">
                      {formatScore(line.home, line.away)}
                    </span>
                    <span className="h-1.5 overflow-hidden rounded-full bg-border/70">
                      <span
                        className="block h-full rounded-full bg-win"
                        style={{ width: `${Math.min(100, line.probability * 500)}%` }}
                      />
                    </span>
                    <span className="text-right text-xs font-semibold text-muted tabular-nums">
                      {pct(line.probability)}
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          );
        })}
      </div>
    </section>
  );
}
