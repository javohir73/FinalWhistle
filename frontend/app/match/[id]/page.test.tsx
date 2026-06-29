/** Match detail page tests — server component (SSR) output. */
import { render, screen } from "@testing-library/react";
import MatchDetailPage from "./page";
import { getMatchServer, getMatchSummary, getMatchSummaryServer, getMatchLineups, getModelRecordServer } from "@/lib/api";
import type { Prediction } from "@/lib/types";

jest.mock("@/lib/api");
const mockGet = getMatchServer as jest.MockedFunction<typeof getMatchServer>;
const mockSummaryServer = getMatchSummaryServer as jest.MockedFunction<typeof getMatchSummaryServer>;
const mockSummary = getMatchSummary as jest.MockedFunction<typeof getMatchSummary>;
const mockLineups = getMatchLineups as jest.MockedFunction<typeof getMatchLineups>;
const mockModelRecord = getModelRecordServer as jest.MockedFunction<typeof getModelRecordServer>;

// Recharts needs a non-zero layout size in jsdom.
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, value: 500 });
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, value: 300 });
});

const prediction: Prediction = {
  match_id: 1,
  model_version: "poisson-elo-v0.1",
  generated_at: "2026-06-06T00:00:00Z",
  teams: { home: "Brazil", away: "Serbia" },
  home_team_id: 10,
  away_team_id: 20,
  group: "Group C",
  group_id: 3,
  stage: "group",
  is_neutral: true,
  kickoff_utc: null,
  venue: null,
  venue_city: null,
  venue_country: null,
  probabilities: { home_win: 0.62, draw: 0.24, away_win: 0.14 },
  predicted_score: { home: 2, away: 0, probability: 0.17 },
  confidence: "High",
  reasons: ["Brazil has a higher Elo rating.", "Strong recent form.", "Won last meeting."],
  top_features: [{ name: "elo_gap", weight: 0.66 }],
  head_to_head: { matches: 1, home_wins: 1, draws: 0, away_wins: 0 },
  odds_comparison: { available: false },
  disclaimer: "For analytics and entertainment only. Not betting advice.",
  goal_markets: null,
};

beforeEach(() => {
  // The scoreboard's secondary fetches: no summary in these SSR tests — the
  // page must render prediction-only.
  mockSummaryServer.mockResolvedValue(null);
  mockSummary.mockRejectedValue(new Error("no api in jsdom"));
  // The Lineups island lazy-fetches client-side; resolve to the clean
  // unavailable placeholder so the SSR-output test renders without a real API.
  mockLineups.mockResolvedValue({
    available: false,
    message: "Lineups are announced ~40 minutes before kickoff.",
    home: null,
    away: null,
    fetched_at: null,
  });
  // Record fetch is secondary — resolve to null (no evaluated matches yet).
  mockModelRecord.mockResolvedValue(null);
});
afterEach(() => jest.resetAllMocks());

it("server-renders teams, probabilities, reasons and odds stub", async () => {
  mockGet.mockResolvedValue(prediction);
  // Render the resolved async server component's output.
  render(await MatchDetailPage({ params: Promise.resolve({ id: "1" }) }));

  expect(screen.getAllByText("Brazil").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("Serbia")).toBeInTheDocument();
  expect(screen.getAllByText("62%").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText(/higher Elo rating/)).toBeInTheDocument();
  // The AI's call leads with the plain verdict sentence.
  expect(screen.getByText(/to win/)).toBeInTheDocument();
});

it("renders the Goals section when goal_markets is present", async () => {
  mockGet.mockResolvedValue({
    ...prediction,
    goal_markets: {
      home: { to_score: 0.86, p2: 0.6, p3: 0.45, p4: 0.38 },
      away: { to_score: 0.39, p2: 0.12, p3: 0.03, p4: 0.01 },
      total: { over_1_5: 0.78, over_2_5: 0.55, over_3_5: 0.3 },
      btts: 0.34,
    },
  });
  render(await MatchDetailPage({ params: Promise.resolve({ id: "1" }) }));
  expect(screen.getByText("Goals")).toBeInTheDocument();
  expect(screen.getByText("Over 2.5")).toBeInTheDocument();
});

it("omits the Goals section when goal_markets is null", async () => {
  mockGet.mockResolvedValue({ ...prediction, goal_markets: null });
  render(await MatchDetailPage({ params: Promise.resolve({ id: "1" }) }));
  expect(screen.queryByText("Goals")).not.toBeInTheDocument();
});

it("calls notFound() for a missing match", async () => {
  mockGet.mockResolvedValue(null);
  await expect(MatchDetailPage({ params: Promise.resolve({ id: "999" }) })).rejects.toThrow();
});

it("renders a prediction-pending view (not 404) when the match exists but has no prediction yet", async () => {
  // A just-drawn knockout tie: no prediction row yet, but the match summary exists.
  mockGet.mockResolvedValue(null);
  mockSummaryServer.mockResolvedValue({
    match_id: 76, stage: "R32", group: null, kickoff_utc: "2026-06-29T17:00:00Z",
    venue: null, venue_city: "Philadelphia", venue_country: "USA", is_neutral: true,
    status: "scheduled", score_home: null, score_away: null, minute: null,
    period: null, injury_time: null, penalty_home: null, penalty_away: null,
    goal_events: [], teams: { home: "Brazil", away: "Japan" },
    predicted_winner: null, probabilities: null, predicted_score: null, confidence: null,
  });

  render(await MatchDetailPage({ params: Promise.resolve({ id: "76" }) }));

  // The matchup renders (no 404), with a clear "prediction on the way" note.
  expect(screen.getAllByText("Brazil").length).toBeGreaterThanOrEqual(1);
  expect(screen.getAllByText("Japan").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText(/prediction on the way/i)).toBeInTheDocument();
});
