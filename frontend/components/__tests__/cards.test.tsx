import { render, screen } from "@testing-library/react";
import { MatchScoreboard } from "@/components/MatchScoreboard";
import * as api from "@/lib/api";
import type { MatchSummary } from "@/lib/types";

// MatchScoreboard polls getMatchSummary on mount — mock it (mirrors scorers.test.tsx).
jest.mock("@/lib/api");
const mockGetMatchSummary = api.getMatchSummary as jest.Mock;
const mockGetProbHistory = api.getProbHistory as jest.Mock;

const summary: MatchSummary = {
  match_id: 1, stage: "group", group: "Group A", kickoff_utc: null,
  venue: null, venue_city: null, venue_country: null, is_neutral: true,
  status: "in_play", score_home: 1, score_away: 0, minute: 70, period: "second_half",
  injury_time: null, penalty_home: null, penalty_away: null,
  teams: { home: "Mexico", away: "South Africa" },
  predicted_winner: "Mexico", probabilities: null, predicted_score: null, confidence: null,
  goal_events: [{ minute: 30, side: "home", player: "R. Jimenez", type: "goal" }],
  card_events: [
    { minute: 44, side: "away", player: "T. Mokoena", type: "red" },
    { minute: 20, side: "home", player: "J. Vasquez", type: "yellow" },
    { minute: 55, side: "home", player: "E. Alvarez", type: "yellow" },
  ],
};

beforeEach(() => {
  mockGetMatchSummary.mockResolvedValue(summary);
  mockGetProbHistory.mockResolvedValue({ match_id: 1, points: [], disclaimer: "" });
});

test("red cards join the timeline; yellows are a compact count", () => {
  render(
    <MatchScoreboard
      matchId={1} home="Mexico" away="South Africa"
      probabilities={{ home_win: 0.6, draw: 0.2, away_win: 0.2 }}
      predicted={{ home: 2, away: 0, probability: 0.2 }}
      initialSummary={summary}
    />,
  );
  expect(screen.getByText(/T\. Mokoena/)).toBeInTheDocument();       // red in timeline
  expect(screen.getByText(/🟨 ×2/)).toBeInTheDocument();             // home yellow count
  expect(screen.queryByText(/J\. Vasquez/)).not.toBeInTheDocument(); // yellows are not timeline entries
  expect(screen.getByText(/R\. Jimenez/)).toBeInTheDocument();       // goals still render
});

test("summary without card_events renders goals as before", () => {
  const legacy: MatchSummary = { ...summary, card_events: undefined };
  mockGetMatchSummary.mockResolvedValue(legacy);
  render(
    <MatchScoreboard
      matchId={1} home="Mexico" away="South Africa"
      probabilities={{ home_win: 0.6, draw: 0.2, away_win: 0.2 }}
      predicted={{ home: 2, away: 0, probability: 0.2 }}
      initialSummary={legacy}
    />,
  );
  expect(screen.getByText(/R\. Jimenez/)).toBeInTheDocument();
  expect(screen.queryByText(/🟨/)).not.toBeInTheDocument();
});
