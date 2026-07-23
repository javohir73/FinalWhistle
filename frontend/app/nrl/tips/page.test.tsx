/** NRL tips page -- server component (SSR) output. */
import { render, screen } from "@testing-library/react";
import NrlTipsPage from "./page";
import { getNrlTipsheetServer } from "@/lib/api";
import type { NrlTipsheet } from "@/lib/types";

jest.mock("@/lib/api");
const mockTipsheet = getNrlTipsheetServer as jest.MockedFunction<typeof getNrlTipsheetServer>;

const fixtures: NrlTipsheet = {
  season: 2026,
  round: 2,
  matches: [{
    id: 5, match_no: 1, kickoff_utc: "2026-03-12T00:00:00+00:00",
    venue: "AAMI Park", home: "Storm", away: "Eels",
    home_team_id: 1, away_team_id: 2, score_home: null, score_away: null,
    status: "scheduled",
    prediction: {
      p_home: 0.6, p_draw: 0.01, p_away: 0.39, expected_margin: 3.0,
      model_version: "nrl-elo-v0.1", created_at: "2026-03-01T00:00:00+00:00",
      is_shadow: true, pick: "home", pick_confidence: 0.6,
    },
  }],
  record: {
    evaluated_matches: 12, winner_accuracy: 0.75, winner_accuracy_ci95: [0.45, 0.92],
    avg_log_loss: 0.52, avg_brier: 0.31, best_streak: 4, last_updated: "2026-07-20T10:00:00+00:00",
  },
  worst_miss: {
    season: 2026, round: 1, home: "Storm", away: "Eels", score_home: 12, score_away: 24,
    pick: "home", pick_team: "Storm", pick_probability: 0.8, winner: "away", winner_team: "Eels",
  },
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

afterEach(() => jest.resetAllMocks());

it("renders the round heading and the tipsheet block", async () => {
  mockTipsheet.mockResolvedValue(fixtures);
  render(await NrlTipsPage());

  expect(screen.getByRole("heading", { name: "NRL tips" })).toBeInTheDocument();
  expect(screen.getByText("Round 2 · 2026")).toBeInTheDocument();
  expect(screen.getByText("Storm")).toBeInTheDocument();
  expect(mockTipsheet).toHaveBeenCalledWith();
});

it("calls notFound() when no NRL data is loaded yet", async () => {
  mockTipsheet.mockResolvedValue(null);
  await expect(NrlTipsPage()).rejects.toThrow();
});

it("renders gracefully when nothing is graded and no match has a prediction yet", async () => {
  mockTipsheet.mockResolvedValue({
    ...fixtures,
    matches: [{ ...fixtures.matches[0], prediction: null }],
    record: {
      evaluated_matches: 0, winner_accuracy: null, winner_accuracy_ci95: null,
      avg_log_loss: null, avg_brier: null, best_streak: 0, last_updated: null,
    },
    worst_miss: null,
  });
  render(await NrlTipsPage());

  expect(screen.getByText("Prediction arriving before kickoff.")).toBeInTheDocument();
  expect(screen.getByText(/No graded matches yet this season/)).toBeInTheDocument();
  expect(screen.queryByText(/worst miss/)).not.toBeInTheDocument();
});
