/** NRL round page tests — server component (SSR) output. The tipsheet fetch
 *  defaults to null in beforeEach so every pre-existing assertion keeps
 *  exercising the plain fixture-grid fallback unchanged; a dedicated test
 *  below covers the TipsheetBlock taking over when the endpoint succeeds. */
import { render, screen } from "@testing-library/react";
import NrlRoundPage from "./page";
import { getNrlMatchesServer, getNrlTipsheetServer } from "@/lib/api";
import type { NrlMatchesResponse, NrlTipsheet } from "@/lib/types";

jest.mock("@/lib/api");
const mockMatches = getNrlMatchesServer as jest.MockedFunction<typeof getNrlMatchesServer>;
const mockTipsheet = getNrlTipsheetServer as jest.MockedFunction<typeof getNrlTipsheetServer>;

const fixtures: NrlMatchesResponse = {
  season: 2026,
  rounds: [
    { round: 18, matches: [] },
    {
      round: 19,
      matches: [{
        id: 42, match_no: 3, kickoff_utc: "2026-07-11T09:35:00+00:00",
        venue: "Leichhardt Oval", home: "Wests Tigers", away: "Warriors",
        home_team_id: 17, away_team_id: 16, score_home: null, score_away: null,
        status: "scheduled", prediction: null,
      }],
    },
    { round: 20, matches: [] },
  ],
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

const tipsheet: NrlTipsheet = {
  season: 2026,
  round: 19,
  matches: [{
    id: 42, match_no: 3, kickoff_utc: "2026-07-11T09:35:00+00:00",
    venue: "Leichhardt Oval", home: "Wests Tigers", away: "Warriors",
    home_team_id: 17, away_team_id: 16, score_home: null, score_away: null,
    status: "scheduled",
    prediction: {
      p_home: 0.55, p_draw: 0.02, p_away: 0.43, expected_margin: 2.0,
      model_version: "nrl-elo-v0.1", created_at: "2026-07-01T00:00:00+00:00",
      is_shadow: false, pick: "home", pick_confidence: 0.55,
    },
  }],
  record: {
    evaluated_matches: 5, winner_accuracy: 0.6, winner_accuracy_ci95: [0.3, 0.85],
    avg_log_loss: 0.6, avg_brier: 0.35, best_streak: 2, last_updated: null,
  },
  worst_miss: null,
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

const params = (n = "19") => Promise.resolve({ n });

beforeEach(() => {
  mockTipsheet.mockResolvedValue(null);
});
afterEach(() => jest.resetAllMocks());

it("renders the round heading and its fixtures", async () => {
  mockMatches.mockResolvedValue(fixtures);
  render(await NrlRoundPage({ params: params() }));

  expect(screen.getByRole("heading", { name: "Round 19" })).toBeInTheDocument();
  expect(screen.getByText("Wests Tigers")).toBeInTheDocument();
});

it("links to the previous and next rounds", async () => {
  mockMatches.mockResolvedValue(fixtures);
  render(await NrlRoundPage({ params: params() }));

  const links = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
  expect(links).toContain("/nrl/round/18");
  expect(links).toContain("/nrl/round/20");
});

it("hides the previous link on the first round", async () => {
  mockMatches.mockResolvedValue(fixtures);
  render(await NrlRoundPage({ params: params("18") }));

  const links = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
  expect(links).not.toContain("/nrl/round/17");
  expect(links).toContain("/nrl/round/19");
});

it("calls notFound() for a round the API doesn't have", async () => {
  mockMatches.mockResolvedValue(fixtures);
  await expect(NrlRoundPage({ params: params("99") })).rejects.toThrow();
});

it("calls notFound() for a non-numeric round without hitting the API", async () => {
  await expect(NrlRoundPage({ params: params("abc") })).rejects.toThrow();
  expect(mockMatches).not.toHaveBeenCalled();
});

it("renders the TipsheetBlock, season record and all, once the tipsheet endpoint succeeds", async () => {
  mockMatches.mockResolvedValue(fixtures);
  mockTipsheet.mockResolvedValue(tipsheet);
  render(await NrlRoundPage({ params: params() }));

  expect(mockTipsheet).toHaveBeenCalledWith(2026, 19);
  expect(screen.getByText("Wests Tigers")).toBeInTheDocument();
  expect(screen.getByText(/5 graded/)).toBeInTheDocument();
});
