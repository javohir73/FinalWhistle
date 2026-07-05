import { render, screen } from "@testing-library/react";
import { RecordView } from "@/components/RecordView";
import type { ModelRecord } from "@/lib/types";

// recharts + ResponsiveContainer needs layout jsdom lacks; the chart has its own
// test, so stub it here and assert the section renders.
jest.mock("@/components/CalibrationChart", () => ({
  CalibrationChart: () => <div data-testid="calibration-chart" />,
}));

const base: ModelRecord = {
  evaluated_matches: 48,
  winner_accuracy: 0.58,
  winner_accuracy_ci95: [0.44, 0.71],
  exact_score_rate: 0.125,
  exact_score_ci95: [0.05, 0.25],
  winners_correct: 28,
  exact_score_hits: 6,
  avg_brier: 0.59,
  avg_log_loss: 0.98,
  calibration: [{ mean_predicted: 0.5, empirical_freq: 0.52, count: 20 }],
  best_calls: [
    { match_id: 1, label: "Mexico 2–0 South Africa", predicted_score: null,
      prob_assigned: 0.81, winner_correct: true, exact_score_correct: true, brier: 0.05, log_loss: 0.21 },
  ],
  biggest_misses: [
    { match_id: 2, label: "Germany 1–2 Japan", predicted_score: null,
      prob_assigned: 0.7, winner_correct: false, exact_score_correct: false, brier: 0.9, log_loss: 1.6 },
  ],
  last_updated: "2026-07-05T00:00:00",
  model_version: "poisson-elo-v0.1",
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

it("shows winner accuracy with its CI and sample size", () => {
  render(<RecordView record={base} />);
  expect(screen.getByText(/58%/)).toBeInTheDocument();
  expect(screen.getByText(/95% CI 44–71%/)).toBeInTheDocument();
  expect(screen.getByText(/n=48/)).toBeInTheDocument();
});

it("renders the honest empty state at n=0 with no CI", () => {
  render(<RecordView record={{
    ...base, evaluated_matches: 0, winner_accuracy: null, winner_accuracy_ci95: null,
    exact_score_rate: null, exact_score_ci95: null, winners_correct: 0, exact_score_hits: 0,
    best_calls: [], biggest_misses: [],
  }} />);
  expect(screen.getByText(/No matches scored yet/)).toBeInTheDocument();
  expect(screen.queryByText(/95% CI/)).not.toBeInTheDocument();
});

it("flags a small sample under 30", () => {
  render(<RecordView record={{ ...base, evaluated_matches: 12 }} />);
  expect(screen.getByText(/Small sample \(12 matches\)/)).toBeInTheDocument();
});

it("surfaces both best calls and biggest misses", () => {
  render(<RecordView record={base} />);
  expect(screen.getByText(/Mexico 2–0 South Africa/)).toBeInTheDocument();
  expect(screen.getByText(/Germany 1–2 Japan/)).toBeInTheDocument();
});
