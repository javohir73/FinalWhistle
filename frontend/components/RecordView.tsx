import Link from "next/link";
import { CalibrationChart } from "@/components/CalibrationChart";
import { cn } from "@/lib/utils";
import type { ModelRecord, ModelRecordEntry } from "@/lib/types";

const SMALL_SAMPLE = 30;
const pct = (x: number) => `${Math.round(x * 100)}%`;

/** "58% · 95% CI 44–71% · n=48" — the interval IS the honesty.
 *  `sampleFormat` distinguishes the two hero stats' rendered sample-size text
 *  (both share the same n, so the DOM text must not collide between boxes). */
function rateLine(
  rate: number | null,
  ci: [number, number] | null,
  n: number,
  sampleFormat: (n: number) => string = (n) => `n=${n}`
): string {
  if (rate == null || ci == null) return "—";
  return `${pct(rate)} · 95% CI ${Math.round(ci[0] * 100)}–${pct(ci[1])} · ${sampleFormat(n)}`;
}

export function RecordView({ record }: { record: ModelRecord }) {
  if (record.evaluated_matches === 0) {
    return (
      <section className="glass rounded-2xl p-6 text-center">
        <h2 className="font-display text-lg font-bold">No matches scored yet</h2>
        <p className="mt-2 text-sm text-muted">
          This fills in as WC26 fixtures finish — every prediction is graded on the
          score after it&apos;s played, never adjusted with hindsight.
        </p>
      </section>
    );
  }

  const n = record.evaluated_matches;

  return (
    <div className="space-y-8">
      {/* Hero honesty row */}
      <section className="grid gap-4 sm:grid-cols-2">
        <StatCI title="Winner accuracy" line={rateLine(record.winner_accuracy, record.winner_accuracy_ci95, n)} />
        <StatCI
          title="Exact scores"
          line={rateLine(record.exact_score_rate, record.exact_score_ci95, n, (n) => `${n} scored`)}
          sub={`${record.exact_score_hits} of ${n} scorelines exact`}
        />
      </section>
      {n < SMALL_SAMPLE && (
        <p className="text-center text-xs text-gold">
          Small sample ({n} matches) — treat these with caution; the intervals are wide.
        </p>
      )}

      {/* Sharpness */}
      <section className="glass rounded-2xl p-6">
        <h2 className="font-display text-lg font-bold">How sharp are the probabilities?</h2>
        <div className="mt-4 grid gap-5 sm:grid-cols-2">
          <Metric label="Avg log-loss" value={record.avg_log_loss}
                  gloss="Rewards being confident and right; punishes confident and wrong. Lower is better." />
          <Metric label="Avg Brier" value={record.avg_brier}
                  gloss="Average squared error of the probabilities. Lower is better." />
        </div>
      </section>

      {/* Calibration */}
      <section className="glass rounded-2xl p-6">
        <h2 className="font-display text-lg font-bold">Is a “60%” really 60%?</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          Every call binned by its stated probability, against how often it actually happened.
          An honest forecast hugs the dashed line. Noisy while the sample is small.
        </p>
        <div className="mt-5">
          <CalibrationChart bins={record.calibration} />
        </div>
        <p className="mt-3 text-xs text-muted">Based on {n} scored matches (all win/draw/loss calls).</p>
      </section>

      {/* Best calls / biggest misses */}
      <section className="grid gap-6 sm:grid-cols-2">
        <CallList title="Best calls" entries={record.best_calls} tone="win" />
        <CallList title="Biggest misses" entries={record.biggest_misses} tone="gold" />
      </section>

      {/* Footer */}
      <section className="glass rounded-2xl p-6 text-xs leading-relaxed text-muted">
        <p>
          Model {record.model_version}
          {record.last_updated ? ` · updated ${record.last_updated}` : ""}.
        </p>
        <p className="mt-1">{record.disclaimer}</p>
        <p className="mt-2">
          Historical back-tests and how the forecast is built:{" "}
          <Link href="/methodology" className="text-lime-deep underline-offset-2 hover:underline">Methodology</Link>.
        </p>
      </section>
    </div>
  );
}

function StatCI({ title, line, sub }: { title: string; line: string; sub?: string }) {
  return (
    <div className="glass rounded-2xl bg-win/[0.06] p-6 text-center">
      <div className="text-xs uppercase tracking-wider text-muted">{title}</div>
      <div className="mt-2 font-display text-lg font-bold tabular-nums text-foreground">{line}</div>
      {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
    </div>
  );
}

function Metric({ label, value, gloss }: { label: string; value: number | null; gloss: string }) {
  return (
    <div>
      <div className="flex items-baseline gap-2">
        <span className="font-display text-2xl font-extrabold tabular-nums text-lime-deep">
          {value != null ? value.toFixed(3) : "—"}
        </span>
        <span className="text-xs text-muted">{label}</span>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-muted">{gloss}</p>
    </div>
  );
}

function CallList({ title, entries, tone }: { title: string; entries: ModelRecordEntry[]; tone: "win" | "gold" }) {
  return (
    <div className="glass rounded-2xl p-5">
      <h3 className="font-display font-bold">{title}</h3>
      {entries.length === 0 ? (
        <p className="mt-2 text-sm text-muted">None yet.</p>
      ) : (
        <ul className="mt-3 space-y-2 text-sm">
          {entries.map((e) => (
            <li key={e.match_id} className="flex items-baseline justify-between gap-3">
              <span className="text-foreground/90">{e.label}</span>
              <span className={cn("shrink-0 tabular-nums", tone === "win" ? "text-lime-deep" : "text-gold")}>
                {e.prob_assigned != null ? pct(e.prob_assigned) : "—"} {e.winner_correct ? "✓" : "✗"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
