/** Research page tests — experimental banner, data and no-data states. */
import { render, screen } from "@testing-library/react";
import MarketBenchmarkPage from "./page";
import { getMarketBenchmarkServer } from "@/lib/api";
import type { MarketBenchmarkResponse } from "@/lib/types";

jest.mock("@/lib/api");
const mockGet = getMarketBenchmarkServer as jest.MockedFunction<
  typeof getMarketBenchmarkServer
>;

const response: MarketBenchmarkResponse = {
  experimental: true,
  status: "ok",
  artifact: {
    experimental: true,
    generated_at: "2026-08-02T12:00:00+00:00",
    coverage: { eligible_observations: 80 },
    exclusions: { incomplete_1x2_set: 3, no_prekickoff_quote: 2 },
    benchmark: {
      split: { train_matches: 56, holdout_matches: 24 },
      groups: [
        {
          venue: "kalshi",
          n_matches: 60,
          status: "READY",
          min_matches: 50,
          capture_window: {
            first_kickoff: "2026-08-01T16:00:00+00:00",
            last_kickoff: "2026-09-30T16:00:00+00:00",
          },
          model: { log_loss: 0.98, brier: 0.61, n: 60 },
          venue_normalized: { log_loss: 0.95, brier: 0.6, n: 60 },
          baseline_uniform: { log_loss: 1.0986, brier: 0.6667, n: 60 },
          delta_log_loss_model_minus_venue: 0.03,
          delta_ci95_match_clustered: [-0.01, 0.07],
          verdict: "inconclusive",
        },
        {
          venue: "polymarket",
          n_matches: 4,
          status: "NOT_READY",
          min_matches: 50,
          reason: "4 matches < minimum 50",
        },
      ],
    },
    health: {
      heartbeat_freshness_by_venue_worker: {
        "kalshi/worker-a": {
          age_seconds: 300,
          last_completed_at: "2026-08-02T11:55:00+00:00",
        },
      },
    },
  },
};

it("renders the experimental banner, counts, exclusions, CI and NOT_READY state", async () => {
  mockGet.mockResolvedValue(response);
  render(await MarketBenchmarkPage());

  expect(
    screen.getByText(/EXPERIMENTAL \/ SHADOW — research data only/),
  ).toBeInTheDocument();
  expect(screen.getByText(/eligible observations:\s*80/)).toBeInTheDocument();
  expect(screen.getByText(/incomplete_1x2_set: 3/)).toBeInTheDocument();
  expect(
    screen.getByText(/95% CI \[-0.01, 0.07\] \(match-clustered\)/),
  ).toBeInTheDocument();
  expect(screen.getByText(/verdict: inconclusive/)).toBeInTheDocument();
  // The tiny venue is a sample-size statement, never a ranking.
  expect(screen.getByTestId("group-polymarket")).toHaveTextContent(
    "Not enough data: 4 matches (minimum 50)",
  );
  expect(screen.getByText(/kalshi\/worker-a: last cycle/)).toBeInTheDocument();
});

it("shows an honest empty state when no artifact exists", async () => {
  mockGet.mockResolvedValue({
    experimental: true,
    status: "no_data",
    detail: "no benchmark artifact has been generated",
  });
  render(await MarketBenchmarkPage());

  expect(screen.getByTestId("no-data")).toHaveTextContent(
    "No benchmark data yet",
  );
  expect(
    screen.getByText(/EXPERIMENTAL \/ SHADOW — research data only/),
  ).toBeInTheDocument();
});

it("degrades to the empty state when the fetch fails", async () => {
  mockGet.mockRejectedValue(new Error("backend down"));
  render(await MarketBenchmarkPage());

  expect(screen.getByTestId("no-data")).toBeInTheDocument();
});
