import type { Metadata } from "next";
import Link from "next/link";
import { APP_NAME } from "@/lib/constants";
import { CalibrationChart } from "@/components/CalibrationChart";
import data from "@/lib/methodology-data.json";

export const metadata: Metadata = {
  title: `Methodology & accuracy — ${APP_NAME}`,
  description:
    "How FinalWhistle predicts the World Cup, and how accurate it is: calibration curve, log-loss & Brier vs baselines, sample sizes, and honest limitations.",
};

type YearMetrics = (typeof data.years)[number];

const fmt = (n: number) => n.toFixed(3);

function bestLogLoss(y: YearMetrics): "model" | "favorite" | "base_rate" {
  const opts: ["model" | "favorite" | "base_rate", number][] = [
    ["model", y.model.log_loss],
    ["favorite", y.favorite.log_loss],
    ["base_rate", y.base_rate.log_loss],
  ];
  return opts.sort((a, b) => a[1] - b[1])[0][0];
}

export default function MethodologyPage() {
  const beatsBaselines = data.years.filter((y) => bestLogLoss(y) === "model").length;

  return (
    <article className="fade-up mx-auto max-w-2xl space-y-10">
      <header>
        <h1 className="font-display text-4xl font-extrabold tracking-tight">
          Methodology &amp; accuracy
        </h1>
        <p className="mt-3 text-muted">
          In plain terms: how the forecasts are made, and how well they&apos;ve actually
          held up when tested against past World Cups. The deeper metrics are below for
          anyone who wants them.
        </p>
      </header>

      {/* Plain-language summary */}
      <section className="grid gap-4 sm:grid-cols-3">
        <Stat big={`${data.training_matches.toLocaleString()}`} label="Real matches learned from (since 1872)" />
        <Stat big={`${data.backtest_years.join(" & ")}`} label="World Cups it was back-tested on" />
        <Stat big="Well-calibrated" label={`A stated 60% happens ~60% of the time`} />
      </section>

      {/* Calibration */}
      <section className="glass rounded-2xl p-6">
        <h2 className="font-display text-lg font-bold">Is a “60%” really 60%?</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          This is the most important question for any prediction. The chart bins every
          forecast by its stated probability and checks how often those things actually
          happened. If the model is honest, the green line hugs the dashed{" "}
          <span className="text-foreground/80">perfect-calibration</span> line.
        </p>
        <div className="mt-5">
          <CalibrationChart bins={data.reliability} />
        </div>
        <p className="mt-3 text-xs text-muted/70">
          Based on {data.reliability_n.toLocaleString()} probability–outcome pairs across the{" "}
          {data.backtest_years.join(" and ")} World Cups (all win/draw/loss calls).
        </p>
      </section>

      {/* Vs baselines */}
      <section>
        <h2 className="font-display text-lg font-bold">Does it beat the obvious guesses?</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          A model is only useful if it beats simple rules. We compare it to{" "}
          <strong className="text-foreground/80">“always back the favourite”</strong> and{" "}
          <strong className="text-foreground/80">“just use historical base rates.”</strong>{" "}
          Lower is better for log-loss and Brier (they punish confident-but-wrong calls);
          higher is better for accuracy.
        </p>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          The model wins on log-loss in {beatsBaselines} of {data.years.length} back-tested
          tournaments. 2022 was unusually upset-heavy — a useful reminder that no model
          foresees shocks reliably, and we&apos;d rather show that than hide it.
        </p>

        <div className="mt-5 space-y-5">
          {data.years.map((y) => {
            const best = bestLogLoss(y);
            return (
              <div key={y.year} className="glass rounded-2xl p-4 sm:p-5">
                <div className="mb-3 flex items-baseline justify-between">
                  <h3 className="font-display font-bold">World Cup {y.year}</h3>
                  <span className="text-xs text-muted">{y.n_matches} matches</span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-[11px] uppercase tracking-wider text-muted">
                        <th className="px-2 pb-2 text-left font-medium">Approach</th>
                        <th className="px-2 pb-2 text-right font-medium" title="Lower is better">Log-loss</th>
                        <th className="px-2 pb-2 text-right font-medium" title="Lower is better">Brier</th>
                        <th className="px-2 pb-2 text-right font-medium" title="Higher is better">Accuracy</th>
                      </tr>
                    </thead>
                    <tbody>
                      <Row label="FinalWhistle model" m={y.model} highlight={best === "model"} />
                      <Row label="Always the favourite" m={y.favorite} highlight={best === "favorite"} />
                      <Row label="Historical base rate" m={y.base_rate} highlight={best === "base_rate"} />
                    </tbody>
                  </table>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Glossary */}
      <section className="glass rounded-2xl p-6">
        <h2 className="font-display text-lg font-bold">What these numbers mean</h2>
        <dl className="mt-3 space-y-3 text-sm">
          <Term term="Calibration">
            Whether stated probabilities match reality. “60% means 60%.” The single most
            important property of a forecaster.
          </Term>
          <Term term="Log-loss">
            Rewards being confident <em>and</em> right; heavily punishes being confident and
            wrong. The model&apos;s primary score. Lower is better.
          </Term>
          <Term term="Brier score">
            The average squared error of the probabilities. Another “lower is better” gauge
            of overall sharpness and calibration.
          </Term>
          <Term term="Baselines">
            Dumb-but-honest reference points. Beating them is the bar any real model must clear.
          </Term>
        </dl>
      </section>

      {/* How it works (recap + link) */}
      <section className="glass rounded-2xl p-6">
        <h2 className="font-display text-lg font-bold">How the forecast is built</h2>
        <ol className="mt-3 space-y-2 text-sm text-foreground/90">
          <li><strong className="text-win">1. Elo ratings</strong> — a strength score per nation, updated after every international since 1872 (hosts get a home bump).</li>
          <li><strong className="text-win">2. Poisson goals</strong> — the Elo gap becomes expected goals, then the probability of every scoreline, giving win/draw/loss odds and a likely result.</li>
          <li><strong className="text-win">3. Monte-Carlo</strong> — groups and the full knockout bracket are simulated thousands of times for qualification and title odds.</li>
        </ol>
        <p className="mt-3 text-sm text-muted">
          More on the step-by-step approach on the{" "}
          <Link href="/about" className="text-win underline-offset-2 hover:underline">How it works</Link> page.
        </p>
      </section>

      {/* Limitations */}
      <section className="glass rounded-2xl border-gold/20 bg-gold/[0.04] p-6">
        <h2 className="font-display text-lg font-bold text-gold">Limitations</h2>
        <ul className="mt-2 list-inside list-disc space-y-1.5 text-sm text-muted">
          <li>Two World Cups (128 matches) is a small sample — treat single-tournament numbers with caution.</li>
          <li>Team-level model: individual player form and injuries aren&apos;t factored in.</li>
          <li>Upset-heavy tournaments (like 2022) are inherently hard; the model can trail simple baselines there.</li>
          <li>Free, open data only: historical results, FIFA rankings, the official WC2026 draw.</li>
        </ul>
        <p className="mt-3 text-xs leading-relaxed text-foreground/70">
          For analytics, research, and entertainment only — not betting advice.
        </p>
      </section>
    </article>
  );
}

function Stat({ big, label }: { big: string; label: string }) {
  return (
    <div className="glass rounded-2xl p-5 text-center">
      <div className="font-display text-2xl font-extrabold tracking-tight text-win">{big}</div>
      <div className="mt-1.5 text-xs text-muted">{label}</div>
    </div>
  );
}

function Row({
  label,
  m,
  highlight,
}: {
  label: string;
  m: { log_loss: number; brier: number; accuracy: number };
  highlight: boolean;
}) {
  return (
    <tr className={`border-t border-border/50 ${highlight ? "bg-win/[0.06]" : ""}`}>
      <td className={`px-2 py-2.5 font-medium ${highlight ? "text-win" : ""}`}>{label}</td>
      <td className="px-2 text-right tabular-nums">{fmt(m.log_loss)}</td>
      <td className="px-2 text-right tabular-nums text-muted">{fmt(m.brier)}</td>
      <td className="px-2 text-right tabular-nums text-muted">{Math.round(m.accuracy * 100)}%</td>
    </tr>
  );
}

function Term({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="font-display font-semibold text-foreground/90">{term}</dt>
      <dd className="text-muted">{children}</dd>
    </div>
  );
}
