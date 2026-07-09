import { render, screen } from "@testing-library/react";
import { MatchScoreboard } from "@/components/MatchScoreboard";
import * as api from "@/lib/api";
import type { MatchSummary } from "@/lib/types";

// MatchScoreboard polls getMatchSummary on mount (useFetch fetches even when
// seeded), so mock the api module — mirrors predictedVsActual.test.tsx.
jest.mock("@/lib/api");
const mockGetMatchSummary = api.getMatchSummary as jest.Mock;
const mockGetProbHistory = api.getProbHistory as jest.Mock;

const summary: MatchSummary = {
  match_id: 1, stage: "group", group: "Group A", kickoff_utc: null,
  venue: null, venue_city: null, venue_country: null, is_neutral: true,
  status: "finished", score_home: 2, score_away: 1, minute: null, period: null,
  injury_time: null, penalty_home: null, penalty_away: null,
  teams: { home: "Mexico", away: "South Africa" },
  predicted_winner: "Mexico", probabilities: null, predicted_score: null, confidence: null,
  goal_events: [
    { minute: 30, side: "home", player: "R. Jimenez", type: "goal" },
    { minute: 70, side: "away", player: "P. Kgatlana", type: "penalty" },
  ],
};

beforeEach(() => {
  mockGetMatchSummary.mockResolvedValue(summary);
  mockGetProbHistory.mockResolvedValue({ match_id: 1, points: [], disclaimer: "" });
});

test("renders goalscorers under the score", () => {
  render(
    <MatchScoreboard
      matchId={1} home="Mexico" away="South Africa"
      probabilities={{ home_win: 0.6, draw: 0.2, away_win: 0.2 }}
      predicted={{ home: 2, away: 0, probability: 0.2 }}
      initialSummary={summary}
    />,
  );
  expect(screen.getByText(/R\. Jimenez/)).toBeInTheDocument();
  expect(screen.getByText(/P\. Kgatlana/)).toBeInTheDocument();
  expect(screen.getByText(/\(pen\)/)).toBeInTheDocument();
});
