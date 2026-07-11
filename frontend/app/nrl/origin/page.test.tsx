/** Origin page tests — server component (SSR) output. */
import { render, screen } from "@testing-library/react";
import OriginPage from "./page";
import { getOriginRecordServer, getOriginSeriesServer } from "@/lib/api";
import type { OriginRecord, OriginSeriesResponse } from "@/lib/types";

jest.mock("@/lib/api");
const mockSeries = getOriginSeriesServer as jest.MockedFunction<typeof getOriginSeriesServer>;
const mockRecord = getOriginRecordServer as jest.MockedFunction<typeof getOriginRecordServer>;

const series: OriginSeriesResponse = {
  season: 2026,
  seasons: [2026, 2025],
  games: [
    {
      round: 1, match_no: 1, kickoff_utc: "2026-05-27T10:05:00+00:00",
      venue: "Accor Stadium", neutral: false, home: "NSW Blues", away: "QLD Maroons",
      score_home: 22, score_away: 20, status: "finished",
      prediction: { p_home: 0.55, p_draw: 0.02, p_away: 0.43, expected_margin: 3.1,
                    model_version: "origin-elo-v0.1", created_at: null, is_shadow: true },
    },
    {
      round: 2, match_no: 2, kickoff_utc: "2026-06-17T10:05:00+00:00",
      venue: "Melbourne Cricket Ground", neutral: true, home: "NSW Blues",
      away: "QLD Maroons", score_home: 24, score_away: 44, status: "finished",
      prediction: null,
    },
    {
      round: 3, match_no: 3, kickoff_utc: "2026-07-08T10:05:00+00:00",
      venue: "Suncorp Stadium", neutral: false, home: "QLD Maroons", away: "NSW Blues",
      score_home: 12, score_away: 30, status: "finished", prediction: null,
    },
  ],
  series: { blues_wins: 2, maroons_wins: 1, drawn_games: 0, winner: "NSW Blues", odds: null },
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

const record: OriginRecord = {
  backtest: {
    model_version: "origin-elo-v0.1", span: [1985, 2024], n: 120,
    winner_accuracy: 0.6, avg_log_loss: 0.66, avg_brier: 0.46,
    home_baseline_accuracy: 0.52, home_prior_log_loss: 0.71,
    generated: "2026-07-11", source: "walk-forward",
  },
  live: { evaluated_matches: 0, winner_accuracy: null, winner_accuracy_ci95: null,
          avg_log_loss: null, avg_brier: null, best_streak: 0, last_updated: null },
  model_version: "origin-elo-v0.1",
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

beforeEach(() => {
  mockSeries.mockResolvedValue(series);
  mockRecord.mockResolvedValue(record);
});

it("renders the series score, winner and games", async () => {
  render(await OriginPage({ searchParams: Promise.resolve({}) }));
  expect(screen.getByRole("heading", { name: /state of origin/i })).toBeInTheDocument();
  expect(screen.getByText(/NSW Blues win the series 2–1/i)).toBeInTheDocument();
  expect(screen.getByText(/Game 2/)).toBeInTheDocument();
  expect(screen.getByText(/neutral/i)).toBeInTheDocument();
});

it("labels the backtest record segment as a backtest", async () => {
  render(await OriginPage({ searchParams: Promise.resolve({}) }));
  expect(screen.getByText(/backtest/i)).toBeInTheDocument();
  expect(screen.getByText(/1985–2024/)).toBeInTheDocument();
  expect(screen.getByText(/no graded live predictions yet/i)).toBeInTheDocument();
});

it("passes the season searchParam through to the fetcher", async () => {
  render(await OriginPage({ searchParams: Promise.resolve({ season: "2025" }) }));
  expect(mockSeries).toHaveBeenCalledWith(2025);
});
