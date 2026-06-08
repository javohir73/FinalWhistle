/** Match detail page tests — server component (SSR) output. */
import { render, screen } from "@testing-library/react";
import MatchDetailPage from "./page";
import { getMatchServer } from "@/lib/api";
import type { Prediction } from "@/lib/types";

jest.mock("@/lib/api");
const mockGet = getMatchServer as jest.MockedFunction<typeof getMatchServer>;

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
};

afterEach(() => jest.resetAllMocks());

it("server-renders teams, probabilities, reasons and odds stub", async () => {
  mockGet.mockResolvedValue(prediction);
  // Render the resolved async server component's output.
  render(await MatchDetailPage({ params: { id: "1" } }));

  expect(screen.getAllByText("Brazil").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("Serbia")).toBeInTheDocument();
  expect(screen.getAllByText("62%").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText(/higher Elo rating/)).toBeInTheDocument();
  expect(screen.getByText(/coming in a later release/i)).toBeInTheDocument();
});

it("calls notFound() for a missing match", async () => {
  mockGet.mockResolvedValue(null);
  await expect(MatchDetailPage({ params: { id: "999" } })).rejects.toThrow();
});
