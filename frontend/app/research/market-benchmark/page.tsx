/** EXPERIMENTAL / SHADOW — venue market benchmark research page.
 *
 *  Renders the operator-generated research artifact verbatim: sample sizes,
 *  capture window, coverage, exclusions, uncertainty, and explicit
 *  not-enough-data states. Nothing here feeds serving, and nothing here may
 *  claim improvement without holdout evidence — a NOT_READY group renders as
 *  exactly that.
 */
import { getMarketBenchmarkServer } from "@/lib/api";
import type { MarketBenchmarkGroup } from "@/lib/types";

export const metadata = {
  title: "Market benchmark (experimental) — FinalWhistle research",
  robots: { index: false },
};

function Group({ group }: { group: MarketBenchmarkGroup }) {
  if (group.status !== "READY") {
    return (
      <section data-testid={`group-${group.venue}`} style={{ margin: "1.5rem 0" }}>
        <h2>{group.venue}</h2>
        <p>
          <strong>Not enough data:</strong> {group.n_matches} matches (minimum{" "}
          {group.min_matches}). No verdict and no ranking on a sample this
          small.
        </p>
      </section>
    );
  }
  const ci = group.delta_ci95_match_clustered;
  return (
    <section data-testid={`group-${group.venue}`} style={{ margin: "1.5rem 0" }}>
      <h2>{group.venue}</h2>
      <p>
        {group.n_matches} holdout matches
        {group.capture_window
          ? ` · kickoffs ${group.capture_window.first_kickoff.slice(0, 10)} → ${group.capture_window.last_kickoff.slice(0, 10)}`
          : null}
      </p>
      <table>
        <thead>
          <tr>
            <th>series</th>
            <th>log loss</th>
            <th>Brier</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>model</td>
            <td>{group.model?.log_loss}</td>
            <td>{group.model?.brier}</td>
          </tr>
          <tr>
            <td>venue (vig-normalized)</td>
            <td>{group.venue_normalized?.log_loss}</td>
            <td>{group.venue_normalized?.brier}</td>
          </tr>
          <tr>
            <td>baseline (uniform)</td>
            <td>{group.baseline_uniform?.log_loss}</td>
            <td>{group.baseline_uniform?.brier}</td>
          </tr>
        </tbody>
      </table>
      <p>
        Δ log loss (model − venue): {group.delta_log_loss_model_minus_venue}
        {ci ? ` · 95% CI [${ci[0]}, ${ci[1]}] (match-clustered)` : " · CI unavailable"}
        {" · "}verdict: {group.verdict}
      </p>
    </section>
  );
}

export default async function MarketBenchmarkPage() {
  let data;
  try {
    data = await getMarketBenchmarkServer();
  } catch {
    data = null;
  }

  return (
    <main style={{ maxWidth: 720, margin: "0 auto", padding: "2rem 1rem" }}>
      <p
        style={{
          border: "1px solid currentColor",
          padding: "0.5rem 0.75rem",
          fontWeight: 600,
        }}
      >
        EXPERIMENTAL / SHADOW — research data only. Nothing on this page feeds
        predictions, and readiness here is never a deployment switch.
      </p>
      <h1>Venue market benchmark</h1>

      {/* `no_data` is the ONLY state that may claim emptiness, so it is
          matched first and by name. Everything else that is not a complete
          success — a fault, a poisoned artifact, an unreachable API, or an
          `ok` carrying no artifact — is a fault on our side. Ordering it this
          way means a status we have never seen fails toward "something is
          wrong" rather than toward "there is nothing here". */}
      {data && data.status === "no_data" ? (
        <p data-testid="no-data">
          No benchmark data yet. An operator generates this artifact with{" "}
          <code>pipeline.run_market_benchmark_report</code>; until then there is
          nothing to show — and nothing is claimed.
        </p>
      ) : !data || data.status !== "ok" || !data.artifact ? (
        <p data-testid="unavailable">
          This benchmark cannot be read right now. That is a fault on our side
          — <strong>not</strong> a statement that no data exists. Whatever was
          published last is still published; this page just could not reach or
          parse it, so nothing is shown rather than something wrong.
        </p>
      ) : (
        <>
          <p>
            Generated {data.artifact.generated_at} · eligible observations:{" "}
            {data.artifact.coverage.eligible_observations ?? 0} · holdout
            matches: {data.artifact.benchmark.split?.holdout_matches ?? 0}
          </p>
          {Object.keys(data.artifact.exclusions).length > 0 ? (
            <details>
              <summary>
                Exclusions (
                {Object.values(data.artifact.exclusions).reduce((a, b) => a + b, 0)}
                {" "}fixture groups)
              </summary>
              <ul>
                {Object.entries(data.artifact.exclusions).map(([reason, count]) => (
                  <li key={reason}>
                    {reason}: {count}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
          {data.artifact.benchmark.groups.length === 0 ? (
            <p data-testid="no-groups">
              No eligible (venue, match) groups yet — capture and resolution
              have not produced scoreable data.
            </p>
          ) : (
            data.artifact.benchmark.groups.map((group) => (
              <Group key={group.venue} group={group} />
            ))
          )}
          {data.artifact.health?.venues ? (
            <details>
              <summary>Mapping & quote coverage</summary>
              {Object.entries(data.artifact.health.venues).map(([venue, health]) => (
                <div key={venue} data-testid={`health-${venue}`}>
                  <h3>{venue}</h3>
                  <ul>
                    <li>
                      markets: {health.markets_total} · mapping:{" "}
                      {Object.entries(health.mapping)
                        .map(([status, count]) => `${status} ${count}`)
                        .join(", ")}
                    </li>
                    <li>
                      fixtures with complete 1X2: {health.fixtures_with_complete_1x2}{" "}
                      of {health.mapped_fixtures} mapped
                      {health.fixtures_incomplete_1x2.length > 0
                        ? ` · incomplete: ${health.fixtures_incomplete_1x2.join(", ")}`
                        : null}
                    </li>
                    <li>
                      fixtures missing a pre-match quote:{" "}
                      {health.fixtures_missing_prematch_quote.length}
                    </li>
                    {Object.entries(health.quote_freshness_by_transport).map(
                      ([transport, freshness]) => (
                        <li key={transport}>
                          last {transport} quote:{" "}
                          {Math.round(freshness.age_seconds / 60)} min ago
                        </li>
                      ),
                    )}
                  </ul>
                </div>
              ))}
            </details>
          ) : null}
          {data.artifact.health?.heartbeat_freshness_by_venue_worker ? (
            <details>
              <summary>Capture freshness</summary>
              <ul>
                {Object.entries(
                  data.artifact.health.heartbeat_freshness_by_venue_worker,
                ).map(([key, value]) => (
                  <li key={key}>
                    {key}: last cycle {value.last_completed_at} (
                    {Math.round(value.age_seconds / 60)} min ago)
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </>
      )}
    </main>
  );
}
