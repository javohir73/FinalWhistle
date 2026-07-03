import type { Metadata } from "next";
import Link from "next/link";
import { APP_NAME } from "@/lib/constants";
import { CalibrationChart } from "@/components/CalibrationChart";
import data from "@/lib/methodology-data.json";
import rawBenchmark from "@/lib/market-benchmark-data.json";

export const metadata: Metadata = {
  title: `Methodology & accuracy — ${APP_NAME}`,
  description:
    "How FinalWhistle predicts the World Cup, and how accurate it is: calibration curve, log-loss & Brier vs baselines, sample sizes, and honest limitations.",
};

type YearMetrics = (typeof data.years)[number];

type Metrics = { log_loss: number; brier: number; accuracy: number };

/** Shape of lib/market-benchmark-data.json (pending until the first run publishes). */
interface MarketBenchmark {
  status: string; // "pending" | "ready" — string to avoid literal-narrowing on comparisons
  dataset: string | null;
  n_matches: number;
  updated_at: string | null;
  model: Metrics | null;
  market: Metrics | null;
  diff_log_loss: number | null;
  diff_ci95: [number, number] | null;
  model_win_rate: number | null;
  mean_edge: number | null;
  verdict: string | null;
}

const bench = rawBenchmark as MarketBenchmark;

const fmt = (n: number) => n.toFixed(3);

/** "2014, 2018 & 2022" */
function listYears(years: number[]): string {
  if (years.length <= 1) return years.join("");
  return `${years.slice(0, -1).join(", ")} & ${years[years.length - 1]}`;
}

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
          Methodology &amp; <span className="text-lime-deep">accuracy</span>
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
        <Stat big={listYears(data.backtest_years)} label="World Cups it was back-tested on" />
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
        <p className="mt-3 text-xs text-muted">
          Based on {data.reliability_n.toLocaleString()} probability–outcome pairs across the{" "}
          {listYears(data.backtest_years)} World Cups (all win/draw/loss calls).
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

      {/* Vs the market (closing line) — the real benchmark (ROADMAP-ENGINE Phase 0) */}
      <section>
        <h2 className="font-display text-lg font-bold">How does it compare to the market?</h2>
        {bench.status !== "ready" ? (
          <div className="glass mt-4 rounded-2xl p-6">
            <p className="text-sm leading-relaxed text-muted">
              Beating naive baselines is the entry bar; the{" "}
              <strong className="text-foreground/80">market&apos;s closing line</strong> — the final
              pre-kickoff bookmaker consensus, stripped of its margin — is the real one. It&apos;s the
              sharpest public forecast there is, so out-predicting it is the only comparison that
              truly counts.
            </p>
            <p className="mt-2 text-sm leading-relaxed text-muted">
              Every WC26 prediction is logged{" "}
              <strong className="text-foreground/80">pre-kickoff, next to the closing odds</strong>,
              so the two can be scored on exactly the same matches. Results publish here after the
              first benchmarked match day.
            </p>
          </div>
        ) : (
          <div className="mt-4 space-y-5">
            <p className="text-sm leading-relaxed text-muted">
              The market&apos;s closing line — the final pre-kickoff bookmaker consensus with its
              margin removed — is the sharpest public forecast there is. Each WC26 prediction is
              logged pre-kickoff next to those odds, so both are scored on exactly the same matches.
            </p>
            <VerdictBadge verdict={bench.verdict!} />
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
                    <Row label="FinalWhistle model" m={bench.model!} highlight={bench.diff_log_loss! < 0} />
                    <Row label="Market closing line" m={bench.market!} highlight={bench.diff_log_loss! > 0} />
                  </tbody>
                </table>
              </div>
            </div>
            <p className="text-xs leading-relaxed text-muted">
              Paired mean log-loss difference (model − market):{" "}
              <span className="tabular-nums text-foreground/80">
                {bench.diff_log_loss! >= 0 ? "+" : ""}{bench.diff_log_loss!.toFixed(4)}
              </span>{" "}
              (95% CI{" "}
              <span className="tabular-nums text-foreground/80">
                [{bench.diff_ci95![0].toFixed(4)}, {bench.diff_ci95![1].toFixed(4)}]
              </span>
              ). Model wins{" "}
              <span className="tabular-nums text-foreground/80">
                {Math.round(bench.model_win_rate! * 100)}%
              </span>{" "}
              of matches head-to-head across {bench.n_matches} games. Updated {bench.updated_at}.
            </p>
          </div>
        )}
      </section>

      {/* What we tested — restraint as a feature */}
      <section className="glass rounded-2xl p-6">
        <h2 className="font-display text-lg font-bold">Why it isn&apos;t more complicated</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          We tested the obvious upgrades the honest way — fitting each only on data
          available <em>before</em> a tournament, then scoring it on that tournament
          (walk-forward, no hindsight):
        </p>
        <ul className="mt-3 list-inside list-disc space-y-1.5 text-sm text-muted">
          <li><span className="text-foreground/80">Probability calibration</span> (temperature scaling) — the fitted setting came out at ≈1.0, i.e. the model is already well-calibrated.</li>
          <li><span className="text-foreground/80">Dixon–Coles draw correction</span> and <span className="text-foreground/80">re-tuned goal parameters</span> — landed back on essentially today&apos;s values; out-of-sample gains were within noise.</li>
          <li><span className="text-foreground/80">Time-decayed (recency-weighted) Elo</span> — helped one World Cup, hurt the others; no net improvement.</li>
        </ul>
        <p className="mt-3 text-sm leading-relaxed text-muted">
          So we kept the simpler, explainable model rather than adding complexity that
          didn&apos;t earn its keep. The real next gain is new <em>signal</em> — squad
          strength, injuries, market priors — not re-tuning what&apos;s here.
        </p>
      </section>

      {/* Model changelog (FR-6.1): one line per shipped model change. */}
      <section className="glass rounded-2xl p-6">
        <h2 className="font-display text-lg font-bold">Model changelog</h2>
        <ul className="mt-3 space-y-1.5 text-sm text-muted">
          <li>
            <span className="text-foreground/80">poisson-elo-v0.2</span> — served
            engine (tuned goal parameters + Dixon&ndash;Coles draw correction, shipped
            mid-group-stage). July 2026: exact-score hits now judged on the
            90-minute score for knockout matches (the basis the model actually
            predicts); every proposed upgrade since is validated walk-forward and
            ships only if it beats this model with statistical confidence — so far
            none has, which is why the version hasn&apos;t moved.
          </li>
        </ul>
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
          <li><strong className="text-lime-deep">1. Elo ratings</strong> — a strength score per nation, updated after every international since 1872 (hosts get a home bump).</li>
          <li><strong className="text-lime-deep">2. Poisson goals</strong> — the Elo gap becomes expected goals, then the probability of every scoreline, giving win/draw/loss odds and a likely result.</li>
          <li><strong className="text-lime-deep">3. Monte-Carlo</strong> — groups and the full knockout bracket are simulated thousands of times for qualification and title odds.</li>
        </ol>
        <p className="mt-3 text-sm text-muted">
          More on the step-by-step approach on the{" "}
          <Link href="/about" className="text-lime-deep underline-offset-2 hover:underline">How it works</Link> page.
        </p>
      </section>

      {/* Model changelog */}
      <section className="glass rounded-2xl p-6">
        <h2 className="font-display text-lg font-bold">Model changelog</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          Every change to the engine, dated, with whether it actually improved the
          back-test — so you can see what&apos;s behind the numbers.
        </p>
        <ol className="mt-4 space-y-4">
          {data.changelog.map((c) => (
            <li key={c.version} className="border-l-2 border-border pl-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-display text-sm font-bold">{c.version}</span>
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${
                    c.status === "current"
                      ? "bg-win/15 text-lime-deep ring-1 ring-win/30"
                      : "chip text-muted"
                  }`}
                >
                  {c.status}
                </span>
                <span className="text-xs text-muted">{c.date}</span>
              </div>
              <p className="mt-1.5 text-sm text-foreground/90">{c.summary}</p>
              <p className="mt-1 text-xs leading-relaxed text-muted">{c.metrics}</p>
            </li>
          ))}
        </ol>
      </section>

      {/* Limitations */}
      <section className="glass rounded-2xl border-gold/20 bg-gold/[0.04] p-6">
        <h2 className="font-display text-lg font-bold text-gold">Limitations</h2>
        <ul className="mt-2 list-inside list-disc space-y-1.5 text-sm text-muted">
          <li>{listYears(data.backtest_years).replace(/&/, "and")} ({data.reliability_n} matches) is still a small sample — treat single-tournament numbers with caution.</li>
          <li>
            The published number is team-level. When an announced XI is available we surface
            player availability as context and log an experimental adjusted forecast — it does
            not move the published number yet (it must first clear our accuracy gate).
          </li>
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
    <div className="glass rounded-2xl bg-win/[0.06] p-5 text-center">
      <div className="font-display text-2xl font-extrabold tracking-tight text-lime-deep">{big}</div>
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
  const label = modelWins
    ? "Model beats market"
    : marketWins
    ? "Market beats model"
    : "No credible difference";
  const cls = modelWins
    ? "bg-win/[0.06] text-lime-deep ring-1 ring-win/40"
    : marketWins
    ? "border-gold/20 bg-gold/[0.04] text-gold ring-1 ring-gold/30"
    : "chip text-muted";
  return (
    <div className={`glass inline-flex items-center rounded-full px-4 py-1.5 text-sm font-bold ${cls}`}>
      {label}
    </div>
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
