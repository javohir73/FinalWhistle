/** NRL club profile page tests — server component (SSR) output. */
import { render, screen } from "@testing-library/react";
import NrlTeamPage from "./page";
import { getNrlTeamServer } from "@/lib/api";
import type { NrlTeamProfile } from "@/lib/types";

jest.mock("@/lib/api");
const mockTeam = getNrlTeamServer as jest.MockedFunction<typeof getNrlTeamServer>;

const profile: NrlTeamProfile = {
  season: 2026,
  team: { id: 16, name: "Warriors", elo_rating: 1573.4 },
  ladder: {
    rank: 3, team_id: 16, name: "Warriors", played: 15,
    wins: 10, draws: 0, losses: 5, points: 20, diff: 168,
  },
  summary: {
    played: 15, wins: 10, draws: 0, losses: 5,
    points_for: 390, points_against: 222,
    avg_for: 26.0, avg_against: 14.8, avg_margin: 11.2,
    home: { wins: 6, draws: 0, losses: 2 },
    away: { wins: 4, draws: 0, losses: 3 },
    streak: { result: "W", length: 3 },
    biggest_win: {
      id: 5201, round: 7, match_no: 52, kickoff_utc: null, venue: null,
      opponent: "Titans", opponent_id: 6, was_home: true,
      score_for: 44, score_against: 6, result: "W", model_called: null,
    },
    biggest_loss: {
      id: 5202, round: 2, match_no: 12, kickoff_utc: null, venue: null,
      opponent: "Storm", opponent_id: 5, was_home: false,
      score_for: 10, score_against: 32, result: "L", model_called: null,
    },
  },
  results: [
    {
      id: 5203, round: 18, match_no: 130, kickoff_utc: "2026-07-04T09:35:00+00:00",
      venue: "Go Media Stadium", opponent: "Broncos", opponent_id: 1,
      was_home: true, score_for: 24, score_against: 12, result: "W",
      model_called: true,
    },
    {
      id: 5204, round: 17, match_no: 121, kickoff_utc: "2026-06-27T07:00:00+00:00",
      venue: "Suncorp Stadium", opponent: "Dolphins", opponent_id: 4,
      was_home: false, score_for: 20, score_against: 18, result: "W",
      model_called: null,
    },
  ],
  upcoming: [
    {
      id: 5205, round: 19, match_no: 134, kickoff_utc: "2026-07-10T10:00:00+00:00",
      venue: "Campbelltown Sports Stadium", opponent: "Wests Tigers",
      opponent_id: 17, was_home: false, win_prob: 0.672,
    },
  ],
  model: { graded: 8, called: 6, accuracy: 0.75 },
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

const params = (id = "16") => Promise.resolve({ id });

afterEach(() => jest.resetAllMocks());

it("server-renders the header with ladder slot, record and streak", async () => {
  mockTeam.mockResolvedValue(profile);
  render(await NrlTeamPage({ params: params() }));

  expect(screen.getAllByText("Warriors").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText(/3rd on the ladder · 10–5–0 · 20 pts · Elo 1573/)).toBeInTheDocument();
  expect(screen.getByText(/3-game winning run/)).toBeInTheDocument();
});

it("renders the season snapshot with splits and bookend results", async () => {
  mockTeam.mockResolvedValue(profile);
  render(await NrlTeamPage({ params: params() }));

  expect(screen.getByText(/Season snapshot · 15 games/)).toBeInTheDocument();
  expect(screen.getByText("26.0")).toBeInTheDocument();
  expect(screen.getByText("+11.2")).toBeInTheDocument();
  expect(screen.getByText("6–2–0")).toBeInTheDocument(); // home W–L–D
  expect(screen.getByText("44–6")).toBeInTheDocument(); // biggest win
});

it("renders the AI grading section from the ledger", async () => {
  mockTeam.mockResolvedValue(profile);
  render(await NrlTeamPage({ params: params() }));

  expect(screen.getByText(/called 6 of 8 graded/)).toBeInTheDocument();
  expect(screen.getByText("75%")).toBeInTheDocument();
});

it("links fixtures and results to their match pages, with win chance and AI verdicts", async () => {
  mockTeam.mockResolvedValue(profile);
  render(await NrlTeamPage({ params: params() }));

  const links = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
  expect(links).toContain("/nrl/match/2026/19/134"); // upcoming
  expect(links).toContain("/nrl/match/2026/18/130"); // result
  expect(screen.getByText("67%")).toBeInTheDocument(); // win chance chip
  expect(screen.getByText("at Wests Tigers")).toBeInTheDocument();
  expect(screen.getByText("✓")).toBeInTheDocument(); // graded result marker
  expect(screen.getByText("24–12")).toBeInTheDocument();
});

it("renders a sparse profile (no games yet) without the stat sections", async () => {
  mockTeam.mockResolvedValue({
    ...profile,
    ladder: null,
    summary: null,
    results: [],
    upcoming: [],
    model: null,
  });
  render(await NrlTeamPage({ params: params() }));

  expect(screen.getAllByText("Warriors").length).toBeGreaterThanOrEqual(1);
  expect(screen.queryByText(/Season snapshot/)).not.toBeInTheDocument();
  expect(screen.queryByText(/graded/)).not.toBeInTheDocument();
  expect(screen.getByText("No recent matches.")).toBeInTheDocument();
});

it("calls notFound() for an unknown team", async () => {
  mockTeam.mockResolvedValue(null);
  await expect(NrlTeamPage({ params: params("9999") })).rejects.toThrow();
});

it("calls notFound() for a non-numeric id without hitting the API", async () => {
  await expect(NrlTeamPage({ params: params("storm") })).rejects.toThrow();
  expect(mockTeam).not.toHaveBeenCalled();
});
