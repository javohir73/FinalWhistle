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
const mockGetProbHistory = api.getProbHistory as jest.Mock;

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

beforeEach(() => {
  mockGetMatchSummary.mockResolvedValue(finished);
  mockGetProbHistory.mockResolvedValue({ match_id: 1, points: [], disclaimer: "" });
});
afterEach(() => {
  jest.resetAllMocks();
  window.localStorage.clear();
});

describe("MatchCard", () => {
  it("shows a plain-language call before kickoff (no result yet)", () => {
    render(<MatchCard match={base} />);
    // home_win 0.6 clears 55% → "Mexico favoured".
    expect(screen.getByText("Mexico favoured")).toBeInTheDocument();
    // ML-model-labelled predicted scoreline, no promoted actual score.
    expect(screen.getByText("ML model")).toBeInTheDocument();
    expect(screen.getByText("1–0")).toBeInTheDocument();
  });

  it("at full time shows actual score, ML-model-labelled prediction, and a verdict", () => {
    render(<MatchCard match={finished} />);
    // Actual score per team row…
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
    // …a "Full time" status pill (not a confidence badge)…
    expect(screen.getByText("Full time")).toBeInTheDocument();
    expect(screen.queryByText(/confidence/i)).not.toBeInTheDocument();
    // …prediction explicitly labelled as the model's call…
    expect(screen.getByText("ML model")).toBeInTheDocument();
    expect(screen.getByText("1–0")).toBeInTheDocument();
    // …and the plain-language scorecard.
    expect(screen.getByText("Called it")).toBeInTheDocument();
  });

  it("shows an amber kickoff-time pill (not a confidence badge) before kickoff", () => {
    // tz is required for the time pill to render in the user's local time.
    render(<MatchCard match={base} tz="UTC" />);
    expect(screen.getByText("7:00 PM")).toBeInTheDocument();
    expect(screen.queryByText(/confidence/i)).not.toBeInTheDocument();
  });

  it("calls out a miss when the favoured side lost", () => {
    render(<MatchCard match={{ ...finished, score_home: 0, score_away: 2 }} />);
    expect(screen.getByText("Upset — we missed it")).toBeInTheDocument();
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
        confidence="High"
        predictedWinner="Mexico"
        caveat="Mexico favoured"
      />,
    );

  it("shows the most-likely score and the AI's call before kickoff", () => {
    mockGetMatchSummary.mockResolvedValue(base);
    renderBoard(base);
    // Scorebug centres the predicted scoreline (upcoming), no promoted actual score.
    expect(screen.getByText("MOST LIKELY SCORE")).toBeInTheDocument();
    // "1–0" appears twice now: the Scorebug centrepiece + the AI's-call scoreline.
    expect(screen.getAllByText("1–0").length).toBeGreaterThanOrEqual(1);
  });

  it("carries the kickoff date and timezone (not just clock time) in the upcoming status line", () => {
    // A fixture weeks out must say which of the tournament's dates it is, and in
    // whose zone — a bare "8:00 PM · venue" can't. Pin the zone via storage so
    // the assertion is deterministic (MatchScoreboard reads tz from useTimezone).
    window.localStorage.setItem(
      "pp:timezone",
      JSON.stringify({ tz: "Europe/London", confirmed: true }),
    );
    mockGetMatchSummary.mockResolvedValue(base);
    render(
      <MatchScoreboard
        matchId={1}
        home="Mexico"
        away="South Africa"
        probabilities={base.probabilities!}
        predicted={base.predicted_score!}
        initialSummary={base}
        kickoffUtc="2026-06-20T19:00:00Z"
        venue="Wembley"
      />,
    );
    // 20:00 London time on Sat 20 Jun 2026 → "Sat 20 Jun · 8:00 PM <tz> · Wembley".
    // The tz label form (BST vs GMT+1) is ICU-version dependent, so assert only
    // that a non-empty zone label sits between the clock and the venue.
    expect(screen.getByText(/20 Jun · 8:00 PM .+ · Wembley/)).toBeInTheDocument();
  });

  it("promotes the live score to the scorebug with the minute", () => {
    mockGetMatchSummary.mockResolvedValue(live);
    renderBoard(live);
    expect(screen.getAllByText("1–0").length).toBeGreaterThanOrEqual(1); // actual (1–0 at 63')
    expect(screen.getByText(/LIVE.*63'/)).toBeInTheDocument();
    expect(screen.getByText(/Model predicted/)).toBeInTheDocument();
  });

  it("shows HT at half-time instead of a ticking minute", () => {
    mockGetMatchSummary.mockResolvedValue(halfTime);
    renderBoard(halfTime);
    expect(screen.getByText(/LIVE.*HT/)).toBeInTheDocument();
    // No minute (a digit + apostrophe); the model's-call eyebrow apostrophe is fine.
    expect(screen.queryByText(/\d+'/)).not.toBeInTheDocument();
  });

  it("shows PENS, the 90-minute score, and the live shootout tally during a shootout", () => {
    mockGetMatchSummary.mockResolvedValue(shootout);
    renderBoard(shootout);
    expect(screen.getByText(/LIVE.*PENS/)).toBeInTheDocument();
    expect(screen.getAllByText("1–1").length).toBeGreaterThanOrEqual(1); // level after 90/ET
    // The running spot-kick tally is the one decisive number while pens are live.
    expect(screen.getByText(/5–4 pens/)).toBeInTheDocument();
  });

  it("at full time shows actual + predicted + verdict together", () => {
    renderBoard(finished);
    expect(screen.getByText("2–0")).toBeInTheDocument(); // actual headline
    expect(screen.getByText("FULL TIME")).toBeInTheDocument();
    expect(screen.getByText("Mexico 1–0 South Africa")).toBeInTheDocument(); // prediction kept visible
    expect(screen.getByText("Result predicted right")).toBeInTheDocument();
  });

  it("falls back to prediction-only when no summary is available", () => {
    mockGetMatchSummary.mockRejectedValue(new Error("offline"));
    renderBoard(null);
    expect(screen.getByText("MOST LIKELY SCORE")).toBeInTheDocument(); // upcoming scorebug
    expect(screen.getAllByText("1–0").length).toBeGreaterThanOrEqual(1); // the AI's-call scoreline
  });
});
