/** Predicted vs actual: the board card labels the model's score and shows a
 *  verdict at full time; the match-page scoreboard promotes the real score to
 *  the headline once a match is live/finished, keeping the prediction visible. */
import { render, screen } from "@testing-library/react";
import { MatchCard } from "@/components/MatchCard";
import { MatchScoreboard } from "@/components/MatchScoreboard";
import * as api from "@/lib/api";
import type { MatchSummary } from "@/lib/types";

jest.mock("@/lib/api");
const mockGetMatchSummary = api.getMatchSummary as jest.Mock;

const base: MatchSummary = {
  match_id: 1,
  stage: "group",
  group: "Group A",
  kickoff_utc: "2026-06-11T19:00:00+00:00",
  venue: "Estadio Azteca",
  venue_city: "Mexico City",
  venue_country: "Mexico",
  is_neutral: false,
  status: "scheduled",
  score_home: null,
  score_away: null,
  minute: null,
  period: null,
  injury_time: null,
  penalty_home: null,
  penalty_away: null,
  teams: { home: "Mexico", away: "South Africa" },
  predicted_winner: "Mexico",
  probabilities: { home_win: 0.6, draw: 0.25, away_win: 0.15 },
  predicted_score: { home: 1, away: 0, probability: 0.18 },
  confidence: "High",
  goal_events: [],
};

// A live match must have a recent kickoff (isLiveNow bounds the live window),
// so derive it relative to now rather than a fixed date that goes stale.
const RECENT_KICKOFF = new Date(Date.now() - 60 * 60_000).toISOString();
const finished: MatchSummary = { ...base, status: "finished", score_home: 2, score_away: 0 };
const live: MatchSummary = {
  ...base, kickoff_utc: RECENT_KICKOFF, status: "in_play",
  score_home: 1, score_away: 0, minute: 63, period: "second_half",
};
const halfTime: MatchSummary = {
  ...base, kickoff_utc: RECENT_KICKOFF, status: "in_play",
  score_home: 1, score_away: 0, minute: null, period: "half_time",
};
const shootout: MatchSummary = {
  ...base, kickoff_utc: RECENT_KICKOFF, status: "in_play", score_home: 1, score_away: 1,
  minute: null, period: "penalty_shootout", penalty_home: 5, penalty_away: 4,
};

beforeEach(() => mockGetMatchSummary.mockResolvedValue(finished));
afterEach(() => jest.resetAllMocks());

describe("MatchCard", () => {
  it("shows the predicted winner row before kickoff (no verdict)", () => {
    render(<MatchCard match={base} />);
    expect(screen.getByText("Winner")).toBeInTheDocument();
    expect(screen.queryByText(/Predicted$/)).not.toBeInTheDocument();
    expect(screen.getByText("1–0")).toBeInTheDocument();
  });

  it("at full time shows actual score, labelled prediction, and a verdict", () => {
    render(<MatchCard match={finished} />);
    // Actual score per team row…
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
    // …prediction explicitly labelled…
    expect(screen.getByText("Predicted")).toBeInTheDocument();
    expect(screen.getByText("1–0")).toBeInTheDocument();
    // …and the model's scorecard.
    expect(screen.getByText("Result predicted right")).toBeInTheDocument();
  });

  it("calls out a miss when the favoured side lost", () => {
    render(<MatchCard match={{ ...finished, score_home: 0, score_away: 2 }} />);
    expect(screen.getByText("Model missed this one")).toBeInTheDocument();
  });
});

describe("MatchScoreboard", () => {
  const renderBoard = (initialSummary: MatchSummary | null) =>
    render(
      <MatchScoreboard
        matchId={1}
        home="Mexico"
        away="South Africa"
        homeTeamId={10}
        awayTeamId={20}
        probabilities={base.probabilities!}
        predicted={base.predicted_score!}
        initialSummary={initialSummary}
      />,
    );

  it("shows the predicted score as headline before kickoff", () => {
    mockGetMatchSummary.mockResolvedValue(base);
    renderBoard(base);
    expect(screen.getByText("1–0")).toBeInTheDocument();
    expect(screen.getByText("predicted")).toBeInTheDocument();
  });

  it("promotes the live score to the headline with the minute", () => {
    mockGetMatchSummary.mockResolvedValue(live);
    renderBoard(live);
    expect(screen.getByText("1–0")).toBeInTheDocument(); // actual (1–0 at 63')
    expect(screen.getByText("63'")).toBeInTheDocument();
    expect(screen.getByText(/Model predicted/)).toBeInTheDocument();
  });

  it("shows HT at half-time instead of a ticking minute", () => {
    mockGetMatchSummary.mockResolvedValue(halfTime);
    renderBoard(halfTime);
    expect(screen.getByText("HT")).toBeInTheDocument();
    expect(screen.queryByText(/'/)).not.toBeInTheDocument(); // no minute shown
  });

  it("shows PENS and the shootout tally during a penalty shootout", () => {
    mockGetMatchSummary.mockResolvedValue(shootout);
    renderBoard(shootout);
    expect(screen.getByText("PENS")).toBeInTheDocument();
    expect(screen.getByText(/5–4 pens/)).toBeInTheDocument();
  });

  it("at full time shows actual + predicted + verdict together", () => {
    renderBoard(finished);
    expect(screen.getByText("2–0")).toBeInTheDocument(); // actual headline
    expect(screen.getByText("FT")).toBeInTheDocument();
    expect(screen.getByText("Mexico 1–0 South Africa")).toBeInTheDocument(); // prediction kept visible
    expect(screen.getByText("Result predicted right")).toBeInTheDocument();
  });

  it("falls back to prediction-only when no summary is available", () => {
    mockGetMatchSummary.mockRejectedValue(new Error("offline"));
    renderBoard(null);
    expect(screen.getByText("1–0")).toBeInTheDocument();
    expect(screen.getByText("predicted")).toBeInTheDocument();
  });
});
