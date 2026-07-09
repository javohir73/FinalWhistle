/** NRL match detail page tests — server component (SSR) output. */
import { render, screen } from "@testing-library/react";
import NrlMatchDetailPage from "./page";
import { getNrlLadderServer, getNrlRoundServer } from "@/lib/api";
import type { NrlMatch, NrlMatchesResponse } from "@/lib/types";

jest.mock("@/lib/api");
const mockRound = getNrlRoundServer as jest.MockedFunction<typeof getNrlRoundServer>;
const mockLadder = getNrlLadderServer as jest.MockedFunction<typeof getNrlLadderServer>;

const match: NrlMatch = {
  match_no: 3,
  kickoff_utc: "2026-07-11T09:35:00+00:00",
  venue: "Leichhardt Oval",
  home: "Wests Tigers",
  away: "Warriors",
  home_team_id: 17,
  away_team_id: 16,
  score_home: null,
  score_away: null,
  status: "scheduled",
  prediction: {
    p_home: 0.311,
    p_draw: 0.017,
    p_away: 0.672,
    expected_margin: -5.5,
    model_version: "nrl-elo-v0.1",
    created_at: "2026-07-06T00:00:00Z",
    is_shadow: true,
  },
};

const roundPayload = (m: NrlMatch): NrlMatchesResponse => ({
  season: 2026,
  rounds: [{ round: 19, matches: [m] }],
  disclaimer: "For analytics and entertainment only. Not betting advice.",
});

const params = (season = "2026", round = "19", no = "3") =>
  Promise.resolve({ season, round, no });

beforeEach(() => {
  mockRound.mockResolvedValue(roundPayload(match));
  // Ladder context is secondary — default to none so most tests skip it.
  mockLadder.mockResolvedValue(null);
});
afterEach(() => jest.resetAllMocks());

it("server-renders the matchup, the AI's call, margin and disclaimer", async () => {
  render(await NrlMatchDetailPage({ params: params() }));

  expect(screen.getAllByText("Wests Tigers").length).toBeGreaterThanOrEqual(1);
  expect(screen.getAllByText("Warriors").length).toBeGreaterThanOrEqual(1);
  // Team columns link through to the club profiles.
  const links = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
  expect(links).toContain("/nrl/team/17");
  expect(links).toContain("/nrl/team/16");
  expect(screen.getByText(/Warriors to win · 67%/)).toBeInTheDocument();
  expect(screen.getByText("Warriors by 5.5")).toBeInTheDocument();
  expect(screen.getByText(/Not betting advice/)).toBeInTheDocument();
  expect(screen.getByText(/model nrl-elo-v0.1/)).toBeInTheDocument();
});

it("shows the final score and grades the call once finished", async () => {
  mockRound.mockResolvedValue(
    roundPayload({ ...match, status: "finished", score_home: 12, score_away: 26 }),
  );
  render(await NrlMatchDetailPage({ params: params() }));

  expect(screen.getByText("12–26")).toBeInTheDocument();
  expect(screen.getByText("Full time")).toBeInTheDocument();
  expect(screen.getByText(/Called it/)).toBeInTheDocument();
  // The pre-match call and margin chip make way for the result.
  expect(screen.queryByText(/to win ·/)).not.toBeInTheDocument();
  expect(screen.queryByText(/AI margin/)).not.toBeInTheDocument();
});

it("marks a result the model got wrong as a miss", async () => {
  mockRound.mockResolvedValue(
    roundPayload({ ...match, status: "finished", score_home: 30, score_away: 8 }),
  );
  render(await NrlMatchDetailPage({ params: params() }));
  expect(screen.getByText(/we missed it/)).toBeInTheDocument();
});

it("renders a prediction-pending view (not 404) when the match has no prediction yet", async () => {
  mockRound.mockResolvedValue(roundPayload({ ...match, prediction: null }));
  render(await NrlMatchDetailPage({ params: params() }));

  expect(screen.getAllByText("Wests Tigers").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText(/prediction on the way/i)).toBeInTheDocument();
});

it("shows the two clubs' ladder rows when the ladder is available", async () => {
  mockLadder.mockResolvedValue({
    season: 2026,
    rows: [
      { rank: 4, team_id: 16, name: "Warriors", played: 18, wins: 12, draws: 0, losses: 6, points: 28, diff: 101 },
      { rank: 9, team_id: 5, name: "Storm", played: 18, wins: 9, draws: 0, losses: 9, points: 22, diff: 40 },
      { rank: 14, team_id: 17, name: "Wests Tigers", played: 18, wins: 5, draws: 1, losses: 12, points: 15, diff: -88 },
    ],
    disclaimer: "For analytics and entertainment only. Not betting advice.",
  });
  render(await NrlMatchDetailPage({ params: params() }));

  expect(screen.getByText("Season so far")).toBeInTheDocument();
  // Only the two clubs in this matchup — not the rest of the ladder.
  expect(screen.queryByText("Storm")).not.toBeInTheDocument();
  expect(screen.getByText("28")).toBeInTheDocument();
});

it("calls notFound() when the match_no isn't in the round", async () => {
  await expect(
    NrlMatchDetailPage({ params: params("2026", "19", "99") }),
  ).rejects.toThrow();
});

it("calls notFound() for a round the API doesn't have", async () => {
  mockRound.mockResolvedValue(null);
  await expect(NrlMatchDetailPage({ params: params("2026", "40", "1") })).rejects.toThrow();
});

it("calls notFound() for non-numeric params without hitting the API", async () => {
  await expect(
    NrlMatchDetailPage({ params: params("2026", "abc", "3") }),
  ).rejects.toThrow();
  expect(mockRound).not.toHaveBeenCalled();
});
