import type { Metadata } from "next";
import Link from "next/link";
import data from "@/lib/venue-audit-data.json";

export const metadata: Metadata = {
  title: "World Cup venue calibration — FinalWhistle",
  description: "A reproducible comparison of FinalWhistle, Kalshi, and Polymarket before kickoff.",
};

const pct = (value: number) => `${(value * 100).toFixed(1)}%`;
const metric = (value: number) => value.toFixed(4);

export default function VenueCalibrationPage() {
  return (
    <article className="fade-up mx-auto max-w-3xl space-y-10">
      <header>
        <p className="text-xs font-bold uppercase tracking-wider text-lime-deep">Research audit</p>
        <h1 className="mt-2 font-display text-4xl font-extrabold tracking-tight">
          The market was the harder benchmark
        </h1>
        <p className="mt-3 leading-relaxed text-muted">
          Across the 2026 World Cup, FinalWhistle was credibly behind Kalshi before kickoff
          and did not credibly beat Polymarket. That is the result, not a footnote.
        </p>
      </header>

      <section className="glass rounded-2xl p-5">
        <h2 className="font-display text-lg font-bold">Model versus each venue</h2>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs uppercase tracking-wide text-muted">
              <th className="pb-2">Predictor</th><th className="pb-2 text-right">Matches</th>
              <th className="pb-2 text-right">Favourite hit</th><th className="pb-2 text-right">Log loss</th>
              <th className="pb-2 text-right">Brier</th>
            </tr></thead>
            <tbody>
              {Object.entries(data.venues).map(([name, result]) => (
                <tr className="border-t border-border/50" key={name}>
                  <td className="py-3 capitalize">{name}</td><td className="text-right">{result.n_matches}</td>
                  <td className="text-right">{pct(result.venue.favorite_hit_rate)}</td>
                  <td className="text-right">{metric(result.venue.log_loss)}</td>
                  <td className="text-right">{metric(result.venue.brier)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-4 text-sm text-muted">
          Model − Kalshi log-loss difference: +{metric(data.venues.kalshi.diff_log_loss)},
          CI95 [{data.venues.kalshi.diff_ci95.map(metric).join(", ")}]. The interval is entirely
          above zero, so Kalshi was credibly better on this sample.
        </p>
        <p className="mt-2 text-sm text-muted">
          Model − Polymarket: +{metric(data.venues.polymarket.diff_log_loss)}, CI95
          [{data.venues.polymarket.diff_ci95.map(metric).join(", ")}]. It crosses zero: inconclusive,
          leaning behind—not evidence that the model won.
        </p>
      </section>

      <section className="grid gap-4 sm:grid-cols-3">
        <Stat value={`${(data.cross_venue.median_max_outcome_divergence * 100).toFixed(1)}¢`} label="Median venue divergence" />
        <Stat value={`${data.cross_venue.favorite_disagreements}/${data.cross_venue.n_matches}`} label="Favourite disagreements" />
        <Stat value={metric(data.cross_venue.log_loss.consensus)} label="Naive consensus log loss" />
      </section>

      <section>
        <h2 className="font-display text-lg font-bold">What was measured</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          All probabilities were normalized to remove the venue margin and graded on the
          regulation-time home/draw/away result. Venue inclusion required all three outcomes.
          The snapshots were reconstructed post-hoc at different fidelities, so they were not
          simultaneous quotes.
        </p>
        <p className="mt-3 text-sm leading-relaxed text-muted">
          This says nothing yet about in-play prices, spreads, first-half markets, correct
          scores, both-teams-to-score, or totals. The 50/50 venue consensus was slightly worse
          than Kalshi alone; it is useful for robustness, not presented as an accuracy gain.
        </p>
      </section>

      <footer className="glass rounded-2xl p-5 text-sm text-muted">
        Reproduce with <code>PYTHONPATH=backend:. python -m pipeline.publish_venue_audit</code>.
        Source data and limitations are summarized in the{" "}
        <Link className="text-lime-deep underline" href="/research/venue-calibration/evidence">
          evidence card
        </Link>.
        This page is information and research only, not betting advice.
      </footer>
    </article>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return <div className="glass rounded-2xl p-5"><div className="font-display text-2xl font-extrabold">{value}</div><div className="mt-1 text-xs text-muted">{label}</div></div>;
}
