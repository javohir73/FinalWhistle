/** Match detail page tests — server component (SSR) output. */
import { render, screen } from "@testing-library/react";
import MatchDetailPage from "./page";
import { getMatchServer, getMatchSummary, getMatchSummaryServer, getModelRecordServer } from "@/lib/api";
import type { Prediction } from "@/lib/types";

jest.mock("@/lib/api");
const mockGet = getMatchServer as jest.MockedFunction<typeof getMatchServer>;
const mockSummaryServer = getMatchSummaryServer as jest.MockedFunction<typeof getMatchSummaryServer>;
const mockSummary = getMatchSummary as jest.MockedFunction<typeof getMatchSummary>;
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
  scoreline_distribution: {
    expected_goals: { home: 1.82, away: 0.74 },
    by_outcome: {
      home: [
        { home: 2, away: 0, probability: 0.17, outcome: "home" },
        { home: 1, away: 0, probability: 0.14, outcome: "home" },
      ],
      draw: [
        { home: 1, away: 1, probability: 0.11, outcome: "draw" },
      ],
      away: [
        { home: 0, away: 1, probability: 0.07, outcome: "away" },
      ],
    },
  },
  confidence: "High",
  reasons: ["Brazil has a higher Elo rating.", "Strong recent form.", "Won last meeting."],
  top_features: [{ name: "elo_gap", weight: 0.66 }],
  head_to_head: { matches: 1, home_wins: 1, draws: 0, away_wins: 0 },
  odds_comparison: { available: false },
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

beforeEach(() => {
  // The scoreboard's secondary fetches: no summary in these SSR tests — the
  // page must render prediction-only.
  mockSummaryServer.mockResolvedValue(null);
  mockSummary.mockRejectedValue(new Error("no api in jsdom"));
  // Record fetch is secondary — resolve to null (no evaluated matches yet).
  mockModelRecord.mockResolvedValue(null);
});
afterEach(() => jest.resetAllMocks());

it("server-renders teams, probabilities, reasons and odds stub", async () => {
  mockGet.mockResolvedValue(prediction);
  // Render the resolved async server component's output.
  render(await MatchDetailPage({ params: { id: "1" } }));

  expect(screen.getAllByText("Brazil").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("Serbia")).toBeInTheDocument();
  expect(screen.getAllByText("62%").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("Scoreline distribution")).toBeInTheDocument();
  expect(screen.getByText(/xG Brazil 1\.82/)).toBeInTheDocument();
  expect(screen.getAllByText("Home win").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText(/higher Elo rating/)).toBeInTheDocument();
  expect(screen.getByText(/coming in a later release/i)).toBeInTheDocument();
});

it("calls notFound() for a missing match", async () => {
  mockGet.mockResolvedValue(null);
  await expect(MatchDetailPage({ params: { id: "999" } })).rejects.toThrow();
});
