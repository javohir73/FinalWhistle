import type { MarketBenchmark } from "@/lib/types";

const fmt = (n: number) => n.toFixed(3);

export function MarketComparison({ bench }: { bench: MarketBenchmark }) {
  if (bench.status !== "ready" || !bench.model || !bench.market) {
    return (
      <div className="glass mt-4 rounded-2xl p-6">
        <p className="text-sm leading-relaxed text-muted">
          Beating naive baselines is the entry bar; the{" "}
          <strong className="text-foreground/80">market&apos;s final pre-kickoff consensus</strong>{" "}
          — the sharpest public forecast there is, with its margin removed — is the real one.
        </p>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          Every WC26 prediction is logged{" "}
          <strong className="text-foreground/80">pre-kickoff, next to the consensus odds we captured</strong>,
          so the two are scored on exactly the same matches. Results publish here after the
          first benchmarked match day.
        </p>
      </div>
    );
  }

  const modelWins = bench.diff_log_loss !== null && bench.diff_log_loss < 0;
  return (
    <div className="mt-4 space-y-5">
      <p className="text-sm leading-relaxed text-muted">
        The market&apos;s final pre-kickoff consensus we captured — margin removed — is the
        sharpest public forecast there is. Each WC26 prediction is logged pre-kickoff next to
        those odds, so both are scored on exactly the same matches.
      </p>
      <VerdictBadge verdict={bench.verdict ?? ""} />
      <div className="glass rounded-2xl p-4 sm:p-5">
        <div className="mb-3 flex items-baseline justify-between">
          <h3 className="font-display font-bold">Model vs. market</h3>
          <span className="text-xs text-muted">{bench.n_matches} matches</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[11px] uppercase tracking-wider text-muted">
                <th className="px-2 pb-2 text-left font-medium">Predictor</th>
                <th className="px-2 pb-2 text-right font-medium" title="Lower is better">Log-loss</th>
                <th className="px-2 pb-2 text-right font-medium" title="Lower is better">Brier</th>
                <th className="px-2 pb-2 text-right font-medium" title="Higher is better">Accuracy</th>
              </tr>
            </thead>
            <tbody>
              <MetricRow label="FinalWhistle model" m={bench.model} highlight={modelWins} />
              <MetricRow label="Market consensus" m={bench.market} highlight={!modelWins} />
            </tbody>
          </table>
        </div>
      </div>
      {bench.diff_log_loss !== null && bench.diff_ci95 && (
        <p className="text-xs leading-relaxed text-muted">
          Paired mean log-loss difference (model − market):{" "}
          <span className="tabular-nums text-foreground/80">
            {bench.diff_log_loss >= 0 ? "+" : ""}{bench.diff_log_loss.toFixed(4)}
          </span>{" "}
          (95% CI{" "}
          <span className="tabular-nums text-foreground/80">
            [{bench.diff_ci95[0].toFixed(4)}, {bench.diff_ci95[1].toFixed(4)}]
          </span>
          ). {bench.dataset}. Updated {bench.updated_at}.
        </p>
      )}
    </div>
  );
}

function MetricRow({
  label, m, highlight,
}: {
  label: string;
  m: { log_loss: number; brier: number; accuracy: number };
  highlight: boolean;
}) {
  return (
    <tr className={`border-t border-border/50 ${highlight ? "bg-win/[0.06]" : ""}`}>
      <td className={`px-2 py-2.5 font-medium ${highlight ? "text-lime-deep" : ""}`}>{label}</td>
      <td className="px-2 text-right tabular-nums">{fmt(m.log_loss)}</td>
      <td className="px-2 text-right tabular-nums text-muted">{fmt(m.brier)}</td>
      <td className="px-2 text-right tabular-nums text-muted">{Math.round(m.accuracy * 100)}%</td>
    </tr>
  );
}

function VerdictBadge({ verdict }: { verdict: string }) {
  const modelWins = verdict.startsWith("MODEL BEATS MARKET");
  const marketWins = verdict.startsWith("MARKET BEATS MODEL");
  const label = modelWins ? "Model beats market"
    : marketWins ? "Market beats model" : "No credible difference";
  const cls = modelWins ? "bg-win/[0.06] text-lime-deep ring-1 ring-win/40"
    : marketWins ? "border-gold/20 bg-gold/[0.04] text-gold ring-1 ring-gold/30"
    : "chip text-muted";
  return (
    <div className={`glass inline-flex items-center rounded-full px-4 py-1.5 text-sm font-bold ${cls}`}>
      {label}
    </div>
  );
}
