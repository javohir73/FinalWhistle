/** Regression test for the Floodlight P1 canonical-URL bug: this wrapper's
 *  generateMetadata used to be a bare re-export of the legacy page's
 *  generateMetadata, which hardcodes alternates.canonical to `/match/${id}` --
 *  a path next.config.mjs now 301s straight back to this very page. Assert
 *  the canonical instead resolves to the live /football/{comp}/match/{id}
 *  URL this page actually serves. */
import { generateMetadata } from "./page";
import { getMatchServer } from "@/lib/api";
import type { Prediction } from "@/lib/types";

jest.mock("@/lib/api");
const mockGet = getMatchServer as jest.MockedFunction<typeof getMatchServer>;

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
  reasons: ["Brazil has a higher Elo rating."],
  top_features: [{ name: "elo_gap", weight: 0.66 }],
  head_to_head: { matches: 1, home_wins: 1, draws: 0, away_wins: 0 },
  odds_comparison: { available: false },
  disclaimer: "For analytics and entertainment only. Not betting advice.",
  goal_markets: null,
};

afterEach(() => jest.resetAllMocks());

it("points the canonical at the live /football/{comp}/match/{id} URL, not the redirecting legacy path", async () => {
  mockGet.mockResolvedValue(prediction);
  const meta = await generateMetadata({ params: Promise.resolve({ comp: "wc26", id: "1" }) });

  expect(meta.alternates?.canonical).toBe("/football/wc26/match/1");
  // Title/description still come through from the legacy generateMetadata.
  expect(meta.title).toContain("Brazil vs Serbia");
});

it("still resolves per-competition once other football competitions go live", async () => {
  mockGet.mockResolvedValue(prediction);
  const meta = await generateMetadata({ params: Promise.resolve({ comp: "epl", id: "7" }) });

  expect(meta.alternates?.canonical).toBe("/football/epl/match/7");
});
