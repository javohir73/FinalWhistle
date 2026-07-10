import { render, screen } from "@testing-library/react";
import { ScoringBreakdown } from "./ScoringBreakdown";
import type { NrlMatchStatsResponse } from "@/lib/types";

const stats: NrlMatchStatsResponse = {
  home: {
    tries: 5, conversions: 4, penalties_conceded: 6, errors: 8,
    set_restarts: 4, run_metres: 1650, line_breaks: 6, tackles: 310,
    tackle_efficiency: 91.3,
  },
  away: {
    tries: 3, conversions: 3, penalties_conceded: 8, errors: 11,
    set_restarts: 6, run_metres: 1432, line_breaks: 3, tackles: 345,
    tackle_efficiency: 88.7,
  },
  try_timeline: [],
};

test("renders one labelled row per contract stat with both values", () => {
  render(<ScoringBreakdown stats={stats} />);
  expect(screen.getByText("Tries")).toBeInTheDocument();
  expect(screen.getByText("Run metres")).toBeInTheDocument();
  expect(screen.getByText("Tackle efficiency")).toBeInTheDocument();
  expect(screen.getByText("1,650")).toBeInTheDocument(); // home run metres
  expect(screen.getByText("91.3%")).toBeInTheDocument(); // home efficiency
  expect(screen.getByText("88.7%")).toBeInTheDocument(); // away efficiency
});
