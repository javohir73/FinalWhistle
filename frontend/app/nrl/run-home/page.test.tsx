/** /nrl/run-home -- server component (SSR) output. RunHomePredictor (the
 *  client-side toggle/odds/URL-state half) is stubbed here -- it has its own
 *  dedicated tests -- so this file stays focused on the server shell: ladder,
 *  fixture grouping/filtering, and the season-over empty state. */
import { render, screen } from "@testing-library/react";
import NrlRunHomePage from "./page";
import { getNrlConditionalProjectionsServer, getNrlLadderServer, getNrlMatchesServer } from "@/lib/api";
import type { LadderResponse, NrlConditionalProjectionsResponse, NrlMatchesResponse } from "@/lib/types";

jest.mock("@/lib/api");
const mockLadder = getNrlLadderServer as jest.MockedFunction<typeof getNrlLadderServer>;
const mockMatches = getNrlMatchesServer as jest.MockedFunction<typeof getNrlMatchesServer>;
const mockBaseline = getNrlConditionalProjectionsServer as jest.MockedFunction<typeof getNrlConditionalProjectionsServer>;

jest.mock("@/components/nrl/RunHomePredictor", () => ({
  RunHomePredictor: ({
    season,
    rounds,
  }: {
    season: number;
    rounds: { round: number | null; matches: unknown[] }[];
  }) => <div data-testid="predictor">{`${season}-${rounds.map((r) => r.matches.length).join(",")}`}</div>,
}));

afterEach(() => jest.resetAllMocks());

const ladder: LadderResponse = {
  season: 2026,
  rows: [{ rank: 1, team_id: 1, name: "Storm", played: 20, wins: 16, draws: 0, losses: 4, points: 32, diff: 120 }],
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

const matches: NrlMatchesResponse = {
  season: 2026,
  rounds: [
    {
      round: 20,
      matches: [
        {
          id: 1, match_no: 1, kickoff_utc: "2026-08-01T00:00:00+00:00", venue: "AAMI Park",
          home: "Storm", away: "Eels", home_team_id: 1, away_team_id: 2,
          score_home: null, score_away: null, status: "scheduled", prediction: null,
        },
        {
          id: 2, match_no: 2, kickoff_utc: "2026-07-20T00:00:00+00:00", venue: "Suncorp",
          home: "Broncos", away: "Titans", home_team_id: 3, away_team_id: 4,
          score_home: 20, score_away: 10, status: "finished", prediction: null,
        },
      ],
    },
  ],
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

const baseline: NrlConditionalProjectionsResponse = {
  season: 2026, n_sims: 2000, picks_applied: 0,
  teams: [{ team: "Storm", top8: 0.9, top4: 0.5, minor_premiership: 0.2, expected_points: 40, expected_remaining_wins: 18 }],
};

it("renders the ladder and hands only the remaining fixtures to the predictor", async () => {
  mockLadder.mockResolvedValue(ladder);
  mockMatches.mockResolvedValue(matches);
  mockBaseline.mockResolvedValue(baseline);

  render(await NrlRunHomePage());

  expect(screen.getByRole("heading", { name: "Predict your run home" })).toBeInTheDocument();
  expect(screen.getByText("Storm")).toBeInTheDocument();
  expect(mockBaseline).toHaveBeenCalledWith(2026);
  // Round 20 has 2 matches total but only 1 is scheduled -- the finished one is excluded.
  expect(screen.getByTestId("predictor")).toHaveTextContent("2026-1");
});

it("calls notFound() when the ladder can't load", async () => {
  mockLadder.mockResolvedValue(null);
  mockMatches.mockResolvedValue(matches);
  await expect(NrlRunHomePage()).rejects.toThrow();
});

it("calls notFound() when fixtures can't load", async () => {
  mockLadder.mockResolvedValue(ladder);
  mockMatches.mockResolvedValue(null);
  await expect(NrlRunHomePage()).rejects.toThrow();
});

it("shows an empty state and skips the baseline fetch when no fixtures remain (season over)", async () => {
  mockLadder.mockResolvedValue(ladder);
  mockMatches.mockResolvedValue({
    ...matches,
    rounds: [{ round: 20, matches: [matches.rounds[0].matches[1]] }], // only the finished match
  });

  render(await NrlRunHomePage());

  expect(screen.getByText(/no remaining fixtures left to predict/i)).toBeInTheDocument();
  expect(mockBaseline).not.toHaveBeenCalled();
  expect(screen.queryByTestId("predictor")).not.toBeInTheDocument();
});
