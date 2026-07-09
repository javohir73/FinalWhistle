import type { Metadata } from "next";
import Link from "next/link";
import { APP_NAME } from "@/lib/constants";
import { CalibrationChart } from "@/components/CalibrationChart";
import data from "@/lib/methodology-data.json";
import { getMarketRecordServer, getModelRecordServer } from "@/lib/api";
import { MarketComparison } from "@/components/MarketComparison";
import type { MarketBenchmark, ModelRecord } from "@/lib/types";

export const metadata: Metadata = {
  title: `Methodology & accuracy — ${APP_NAME}`,
  description:
    "How FinalWhistle predicts the World Cup, and how accurate it is: calibration curve, log-loss & Brier vs baselines, sample sizes, and honest limitations.",
};

type YearMetrics = (typeof data.years)[number];

const fmt = (n: number) => n.toFixed(3);

const PENDING_MARKET: MarketBenchmark = {
  status: "pending", dataset: null, n_matches: 0, updated_at: null,
  model: null, market: null, diff_log_loss: null, diff_ci95: null,
  model_win_rate: null, mean_edge: null, verdict: null,
};

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

// The Athletic's public WC26 picking contest, as they reported it on
// 2026-07-08 (matches graded through the round of 16, ~94 picks). A static
// snapshot by design: their numbers are theirs; ours stay live below.
const EXTERNAL_PICKERS = [
  { name: "The algorithm (The Athletic)", accuracy: "69%", correct: 65, streak: 14 },
  { name: "The Athletic's experts", accuracy: "68%", correct: 64, streak: 11 },
  { name: "Wilfred (age 6)", accuracy: "66%", correct: 62, streak: 7 },
  { name: "Reader picks", accuracy: "62%", correct: 58, streak: 5 },
  { name: "Stanley the dog", accuracy: "39%", correct: 37, streak: 4 },
] as const;

export default async function MethodologyPage() {
  const beatsBaselines = data.years.filter((y) => bestLogLoss(y) === "model").length;
  let bench: MarketBenchmark = PENDING_MARKET;
  try {
    bench = (await getMarketRecordServer()) ?? PENDING_MARKET;
  } catch {
    bench = PENDING_MARKET;
  }
  let record: ModelRecord | null = null;
  try {
    record = await getModelRecordServer();
  } catch {
    record = null;
  }

  return (
    <article className="fade-up mx-auto max-w-2xl space-y-10">
      <header>
        <h1 className="font-display text-4xl font-extrabold tracking-tight">
          Methodology &amp; <span className="text-lime-deep">accuracy</span>
        </h1>
        <p className="mt-3 text-muted">
          In plain terms: how the forecasts are made, and how well they&apos;ve actually
          held up when tested against past World Cups. The deeper metrics are below for
          anyone who wants them. For the live WC26 record so far, see the{" "}
          <Link href="/record" className="text-lime-deep underline-offset-2 hover:underline">Track record</Link>.
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

      {/* Vs the market — the real benchmark (ROADMAP-ENGINE Phase 0), live from /api/model/market-record */}
      <section>
        <h2 className="font-display text-lg font-bold">How does it compare to the market?</h2>
        <MarketComparison bench={bench} />
      </section>

      {/* Vs other public predictors — external snapshot vs our live ledger */}
      <section className="glass rounded-2xl p-6">
        <h2 className="font-display text-lg font-bold">How does it compare to other predictors?</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          The Athletic ran this World Cup as a public picking contest — their
          prediction algorithm, their writers, their readers, a six-year-old and a
          dog. Their numbers below are a snapshot of what they published on July 8,
          2026 (picks graded through the round of 16); our row is computed live from
          the same graded ledger as the{" "}
          <Link href="/record" className="text-lime-deep underline-offset-2 hover:underline">Track record</Link>{" "}
          and keeps updating as matches finish.
        </p>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[11px] uppercase tracking-wider text-muted">
                <th className="px-2 pb-2 text-left font-medium">Predictor</th>
                <th className="px-2 pb-2 text-right font-medium">Overall accuracy</th>
                <th className="px-2 pb-2 text-right font-medium">Correct picks</th>
                <th className="px-2 pb-2 text-right font-medium">Best streak</th>
              </tr>
            </thead>
            <tbody>
              <tr className="rounded-lg bg-lime-deep/10 font-medium text-foreground">
                <td className="px-2 py-1.5">FinalWhistle model (live)</td>
                <td className="px-2 py-1.5 text-right">
                  {record?.winner_accuracy != null
                    ? `${(record.winner_accuracy * 100).toFixed(1)}%`
                    : "—"}
                </td>
                <td className="px-2 py-1.5 text-right">
                  {record ? `${record.winners_correct}/${record.evaluated_matches}` : "—"}
                </td>
                <td className="px-2 py-1.5 text-right">{record?.best_streak ?? "—"}</td>
              </tr>
              {EXTERNAL_PICKERS.map((p) => (
                <tr key={p.name} className="text-muted">
                  <td className="px-2 py-1.5">{p.name}</td>
                  <td className="px-2 py-1.5 text-right">{p.accuracy}</td>
                  <td className="px-2 py-1.5 text-right">{p.correct}</td>
                  <td className="px-2 py-1.5 text-right">{p.streak}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs leading-relaxed text-muted">
          Apples-to-oranges caveats, stated plainly: the contests grade slightly
          different match sets (their table implies ~94 picks; we grade every
          finished match with a frozen pre-kickoff prediction), and picking rules
          differ — our headline number grades the 90-minute result, draws
          included, which is a stricter test than knockout-winner-only picks. On
          the advancement basis those contests use for knockouts, our record is{" "}
          {record && record.advancement_matches > 0
            ? `${record.advancement_correct} of ${record.advancement_matches} (${((record.advancement_accuracy ?? 0) * 100).toFixed(1)}%)`
            : "still building as the knockouts finish"}
          . We publish the comparison anyway because pretending benchmarks
          don&apos;t exist is worse than imperfect ones. Source: The Athletic,
          July 2026.
        </p>
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
          <li><span className="text-foreground/80">Probability calibration</span> — plain temperature scaling fitted to ≈1.0 (already calibrated overall), but a <em>segmented</em> calibrator — one correction per rating-gap bracket — did clear the walk-forward gate and shipped in v0.4 (July 2026).</li>
          <li><span className="text-foreground/80">Dixon–Coles draw correction</span> and <span className="text-foreground/80">re-tuned goal parameters</span> — landed back on essentially today&apos;s values; out-of-sample gains were within noise.</li>
          <li><span className="text-foreground/80">Time-decayed (recency-weighted) Elo</span> — helped one World Cup, hurt the others; no net improvement.</li>
        </ul>
        <p className="mt-3 text-sm leading-relaxed text-muted">
          So we kept the simpler, explainable model rather than adding complexity that
          didn&apos;t earn its keep. The real next gain is new <em>signal</em> — squad
          strength, injuries, market priors — not re-tuning what&apos;s here.
        </p>
      </section>

      {/* Model changelog (FR-6.1): one line per shipped model change, newest
          first. poisson-elo-v0.5 is the version actually loaded from
          ml/models/model_params.json and served by generate_predictions —
          the code-verified current version (see ml/models/knockout.py and
          docs/MODEL-V2-DESIGN.md). */}
      <section className="glass rounded-2xl p-6">
        <h2 className="font-display text-lg font-bold">Model changelog</h2>
        <ul className="mt-3 space-y-1.5 text-sm text-muted">
          <li>
            <span className="text-foreground/80">poisson-elo-v0.5</span>{" "}
            <span className="rounded-full bg-win/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-lime-deep ring-1 ring-win/30">current</span>{" "}
            — served engine since July 8, 2026: adds extra-time and
            penalty-shootout resolution for knockout ties (30-minute Dixon&ndash;Coles
            extra time, then a capped Elo-logistic penalty model), needed now
            the bracket has reached the knockout rounds. A suspension /
            rest-days / keeper-availability signal pack shipped alongside it,
            shadow-only — it doesn&apos;t move the published number until it
            clears the same walk-forward gate as everything else.
          </li>
          <li>
            <span className="text-foreground/80">poisson-elo-v0.4</span> — served
            engine from July 8, 2026 until superseded by v0.5 the same day:
            v0.2 plus a segmented probability calibrator (one correction per
            rating-gap bracket, fitted only on matches before this World Cup).
            The one candidate from the July audit that improved held-out log
            loss on every test; a redesigned recent-form signal from the same
            audit failed its gate and ships dark until the evidence is
            consistent.
          </li>
          <li>
            <span className="text-foreground/80">poisson-elo-v0.2</span> — served
            engine until July 2026 (tuned goal parameters + Dixon&ndash;Coles draw
            correction, shipped mid-group-stage). July 2026: exact-score hits now
            judged on the 90-minute score for knockout matches (the basis the model
            actually predicts). Every proposed upgrade is validated walk-forward
            and ships only if it beats the served model with statistical
            confidence.
          </li>
          <li>
            <span className="text-foreground/80">v0.2 study (June 2026, not
            shipped as-is)</span> — walk-forward tested temperature
            calibration, a Dixon&ndash;Coles draw correction, re-tuned goal
            parameters, and time-decayed Elo. Plain temperature fitted &asymp;
            1.0 (already calibrated) and most re-tuning landed back on v0.1
            values; the parts that later earned their keep shipped as v0.2.
          </li>
          <li>
            <span className="text-foreground/80">poisson-elo-v0.1</span> —
            May 2026: original hand-set Elo &rarr; Poisson baseline
            (uncalibrated): the fallback engine and the starting point every
            later tune was measured against.
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

function Term({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="font-display font-semibold text-foreground/90">{term}</dt>
      <dd className="text-muted">{children}</dd>
    </div>
  );
}
