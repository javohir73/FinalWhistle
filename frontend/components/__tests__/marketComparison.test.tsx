import { render, screen } from "@testing-library/react";
import { MarketComparison } from "@/components/MarketComparison";
import type { MarketBenchmark } from "@/lib/types";

const pending: MarketBenchmark = {
  status: "pending", dataset: null, n_matches: 0, updated_at: null,
  model: null, market: null, diff_log_loss: null, diff_ci95: null,
  model_win_rate: null, mean_edge: null, verdict: null,
};

const ready: MarketBenchmark = {
  status: "ready", dataset: "WC26 live (final pre-kickoff consensus we captured)",
  n_matches: 20, updated_at: "2026-07-05T00:00:00+00:00",
  model: { log_loss: 0.98, brier: 0.59, accuracy: 0.6 },
  market: { log_loss: 0.95, brier: 0.57, accuracy: 0.62 },
  diff_log_loss: 0.03, diff_ci95: [-0.01, 0.07], model_win_rate: 0.45, mean_edge: -0.01,
  verdict: "NO CREDIBLE DIFFERENCE (CI straddles 0)",
};

it("shows the pending copy before any benchmarked match", () => {
  render(<MarketComparison bench={pending} />);
  expect(screen.getByText(/results publish here after the first benchmarked match day/i)).toBeInTheDocument();
  expect(screen.queryByText(/Model vs\.? market/i)).not.toBeInTheDocument();
});

it("shows the comparison table and verdict when ready", () => {
  render(<MarketComparison bench={ready} />);
  expect(screen.getByText(/No credible difference/i)).toBeInTheDocument();
  expect(screen.getByText(/20 matches/)).toBeInTheDocument();
  // The honest label renders in both the intro copy and the dataset footnote.
  expect(screen.getAllByText(/final pre-kickoff consensus/i).length).toBeGreaterThan(0);
});
