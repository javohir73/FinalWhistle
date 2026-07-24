/** MatchCard restyle (Floodlight P2 slice p2-s2): the shared football fixture
 *  card keeps its scoreboard behavior (live ring, ProbabilityBar aria-label,
 *  detail link) and gains a `variant="compact"` row for dense lists. */
import { render, screen } from "@testing-library/react";
import { MatchCard } from "@/components/MatchCard";
import type { MatchSummary } from "@/lib/types";

function makeMatch(overrides: Partial<MatchSummary> = {}): MatchSummary {
  return {
    match_id: 11,
    stage: "group",
    group: "Group B",
    kickoff_utc: "2026-06-14T18:00:00+00:00",
    venue: "Lumen Field",
    venue_city: "Seattle",
    venue_country: "USA",
    is_neutral: false,
    status: "scheduled",
    score_home: null,
    score_away: null,
    minute: null,
    period: null,
    injury_time: null,
    penalty_home: null,
    penalty_away: null,
    teams: { home: "Argentina", away: "Japan" },
    predicted_winner: "Argentina",
    probabilities: { home_win: 0.65, draw: 0.2, away_win: 0.15 },
    predicted_score: { home: 2, away: 0, probability: 0.12 },
    confidence: "High",
    goal_events: [],
    ...overrides,
  };
}

describe("MatchCard (full variant, default)", () => {
  it("renders both team names, an accessible probability bar, and links to the match", () => {
    const match = makeMatch();
    render(<MatchCard match={match} />);

    expect(screen.getByText("Argentina")).toBeInTheDocument();
    expect(screen.getByText("Japan")).toBeInTheDocument();

    const bar = screen.getByRole("img");
    expect(bar).toHaveAttribute("aria-label", expect.stringContaining("65%"));

    expect(screen.getByRole("link")).toHaveAttribute("href", "/match/11");
  });

  it("shows the live ring treatment and live label when isLiveNow", () => {
    const liveMatch = makeMatch({
      // Recent kickoff so isLiveNow() reads it as actually live, not stale.
      kickoff_utc: new Date(Date.now() - 30 * 60_000).toISOString(),
      status: "in_play",
      score_home: 1,
      score_away: 1,
      minute: 34,
      period: "first_half",
    });
    render(<MatchCard match={liveMatch} />);

    expect(screen.getByRole("link")).toHaveClass("ring-1", "ring-loss/40");
    expect(screen.getByText("34'")).toBeInTheDocument();
    expect(screen.getByLabelText(/Live, 34'/)).toBeInTheDocument();
  });
});

describe("MatchCard (variant=\"compact\")", () => {
  it("still links to the match detail page and keeps the live ring", () => {
    const liveMatch = makeMatch({
      kickoff_utc: new Date(Date.now() - 10 * 60_000).toISOString(),
      status: "in_play",
      minute: 12,
      period: "first_half",
    });
    render(<MatchCard match={liveMatch} variant="compact" />);

    expect(screen.getByRole("link")).toHaveAttribute("href", "/match/11");
    expect(screen.getByRole("link")).toHaveClass("ring-1", "ring-loss/40");
  });

  it("shows a lime lead percentage for a >=60% favorite", () => {
    const match = makeMatch({ probabilities: { home_win: 0.72, draw: 0.18, away_win: 0.1 } });
    render(<MatchCard match={match} variant="compact" />);

    const lead = screen.getByText("72%");
    expect(lead).toHaveClass("text-lime-deep");
  });

  it("shows a muted lead percentage when no side clears 60%", () => {
    const match = makeMatch({ probabilities: { home_win: 0.42, draw: 0.3, away_win: 0.28 } });
    render(<MatchCard match={match} variant="compact" />);

    const lead = screen.getByText("42%");
    expect(lead).toHaveClass("text-muted");
    expect(lead).not.toHaveClass("text-lime-deep");
  });
});
