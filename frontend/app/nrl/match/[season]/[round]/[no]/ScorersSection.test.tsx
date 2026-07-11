/** ScorersSection: the client island wiring per-player anytime-try-scorer
 *  chances to GET /api/nrl/matches/{id}/scorers (single fetch, no polling --
 *  team lists are static once named). Adapted from the Task 10 brief's
 *  async-server-component design to this codebase's actual
 *  `IntelSectionProps` contract (`{detail, probHistory}`, rendered
 *  synchronously from the "use client" MatchIntelClient) — same drift
 *  Task 9 documented for LiveSection.tsx/LiveSection.test.tsx. */
import { render, screen, waitFor } from "@testing-library/react";
import ScorersSection from "./ScorersSection";
import { getNrlScorersClient } from "@/lib/api";
import type { NrlScorer, NrlMatchDetail } from "@/lib/types";

jest.mock("@/lib/api");
const mockScorers = getNrlScorersClient as jest.MockedFunction<typeof getNrlScorersClient>;

afterEach(() => jest.resetAllMocks());

function detail(status: string): NrlMatchDetail {
  return {
    match: {
      id: 1, season: 2026, round: 19, match_no: 3,
      kickoff_utc: "2026-07-11T09:35:00+00:00", venue: "Suncorp Stadium",
      home: "Broncos", away: "Storm",
      home_team_id: 1, away_team_id: 2,
      score_home: null, score_away: null,
      status,
    },
    prediction: null,
    form: { home: null, away: null },
    h2h: [],
    factors: [],
  };
}

const scorer = (over: Partial<NrlScorer> = {}): NrlScorer => ({
  player: "A. Wing", jersey: 2, position: "WG", unit: "outside backs",
  tries_season: 12, games_season: 15, last10: [{ round: 14, tries: 1 }],
  p_anytime: 0.42, team: "home", ...over,
});

it("renders home and away columns with anytime-try chance, no odds", async () => {
  mockScorers.mockResolvedValue([
    scorer(),
    scorer({ player: "B. Centre", team: "away", p_anytime: 0.31, jersey: 3 }),
  ]);

  render(<ScorersSection detail={detail("scheduled")} probHistory={null} />);

  expect(await screen.findByText("A. Wing")).toBeInTheDocument();
  expect(screen.getByText("B. Centre")).toBeInTheDocument();
  expect(screen.getByText("42%")).toBeInTheDocument();
  expect(screen.queryByText(/odds/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/value/i)).not.toBeInTheDocument();
});

it("renders nothing when the team list is empty", async () => {
  mockScorers.mockResolvedValue([]);

  const { container } = render(
    <ScorersSection detail={detail("scheduled")} probHistory={null} />,
  );
  await waitFor(() => expect(mockScorers).toHaveBeenCalledTimes(1));
  expect(container).toBeEmptyDOMElement();
});

it("shows the quiet unavailable message when the scorers fetch fails", async () => {
  mockScorers.mockRejectedValue(new Error("offline"));

  render(<ScorersSection detail={detail("in_play")} probHistory={null} />);

  expect(await screen.findByText(/try-scorer chances are unavailable/i)).toBeInTheDocument();
});
