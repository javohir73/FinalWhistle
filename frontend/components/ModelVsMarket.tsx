import type { Prediction } from "@/lib/types";
import { ProbabilityBar } from "@/components/ProbabilityBar";

/** Model vs market on the match page: the AI's W/D/L triple stacked against
 *  the market-consensus implied probabilities (median across bookmakers,
 *  margin removed). Renders nothing until an odds snapshot exists for the
 *  match. Probabilities only — no prices, no bookmaker names, and the
 *  standing not-betting-advice framing. (Distinct from MarketComparison,
 *  the methodology page's aggregate benchmark table.) */
export function ModelVsMarket({
  prediction,
  home,
  away,
}: {
  prediction: Prediction;
  home: string;
  away: string;
}) {
  const oc = prediction.odds_comparison;
  if (!oc?.available || !oc.market) return null;
  return (
    <section className="glass rounded-2xl p-6">
      <h2 className="mb-1 font-display text-lg font-bold text-foreground">
        Model vs market
      </h2>
      <p className="mb-4 text-xs leading-relaxed text-muted">
        The AI&apos;s probabilities next to the betting market&apos;s consensus
        (median across bookmakers, margin removed). Disagreement is where the
        model thinks the market is wrong — or vice versa.
      </p>
      <div className="space-y-4">
        <div>
          <div className="mb-1.5 font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
            The AI
          </div>
          <ProbabilityBar probabilities={prediction.probabilities} homeLabel={home} awayLabel={away} />
        </div>
        <div>
          <div className="mb-1.5 font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
            Market consensus
          </div>
          <ProbabilityBar probabilities={oc.market} homeLabel={home} awayLabel={away} />
        </div>
      </div>
      <p className="mt-4 text-[11px] leading-snug text-muted">
        For analytics and entertainment only. Not betting advice.
      </p>
    </section>
  );
}
