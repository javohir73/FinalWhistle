/** Component unit tests (task 6.9). */
import { render, screen } from "@testing-library/react";
import { ProbabilityBar } from "@/components/ProbabilityBar";
import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { OddsCompare } from "@/components/OddsCompare";
import { DisclaimerBanner } from "@/components/DisclaimerBanner";
import { MatchCard } from "@/components/MatchCard";
import { GroupTable } from "@/components/GroupTable";
import { ReasonsList } from "@/components/ReasonsList";
import type { MatchSummary, StandingRow } from "@/lib/types";

describe("ProbabilityBar", () => {
  it("renders an accessible W/D/L summary", () => {
    render(
      <ProbabilityBar probabilities={{ home_win: 0.6, draw: 0.25, away_win: 0.15 }} />,
    );
    const bar = screen.getByRole("img");
    expect(bar).toHaveAttribute("aria-label", expect.stringContaining("60%"));
    expect(bar.getAttribute("aria-label")).toContain("25%");
    expect(bar.getAttribute("aria-label")).toContain("15%");
  });
});

describe("ConfidenceBadge", () => {
  it("shows the level", () => {
    render(<ConfidenceBadge level="High" />);
    expect(screen.getByText(/High confidence/)).toBeInTheDocument();
  });
  it("renders nothing when null", () => {
    const { container } = render(<ConfidenceBadge level={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("OddsCompare", () => {
  it("degrades gracefully when unavailable", () => {
    render(<OddsCompare available={false} />);
    expect(screen.getByText(/coming in a later release/i)).toBeInTheDocument();
  });
  it("renders nothing when available (placeholder for Phase 4)", () => {
    const { container } = render(<OddsCompare available />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("DisclaimerBanner", () => {
  it("states it is not betting advice", () => {
    render(<DisclaimerBanner />);
    expect(screen.getByRole("note")).toHaveTextContent(/not betting advice/i);
  });
});

describe("ReasonsList", () => {
  it("renders all reasons", () => {
    render(<ReasonsList reasons={["A", "B", "C"]} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });
});

describe("MatchCard", () => {
  const match: MatchSummary = {
    match_id: 7,
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
    probabilities: { home_win: 0.78, draw: 0.14, away_win: 0.08 },
    predicted_score: { home: 2, away: 0, probability: 0.12 },
    confidence: "High",
    goal_events: [],
  };

  it("renders matchup, predicted winner, score and links to detail", () => {
    render(<MatchCard match={match} />);
    // "Mexico" appears as the home team and as the predicted winner.
    expect(screen.getAllByText("Mexico").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("South Africa")).toBeInTheDocument();
    expect(screen.getByText("2–0")).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/match/7");
    // The card carries a status pill now, not a confidence badge — even though
    // this fixture has a confidence level, no "… confidence" badge is rendered.
    expect(screen.queryByText(/confidence/i)).not.toBeInTheDocument();
  });

  it("shows a LIVE badge, minute and the running score when in play", () => {
    const liveMatch = {
      ...match,
      // Recent kickoff so isLiveNow() treats it as actually live (not stale).
      kickoff_utc: new Date(Date.now() - 60 * 60_000).toISOString(),
      status: "in_play" as const,
      score_home: 1,
      score_away: 0,
      minute: 67,
      period: "second_half" as const,
    };
    render(<MatchCard match={liveMatch} />);
    expect(screen.getByText("67'")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument(); // home live score
  });
});

describe("GroupTable", () => {
  const standings: StandingRow[] = [
    { team_id: 1, team: "Mexico", projected_points: 6, projected_goals_for: 5, projected_goal_diff: 3, qualification_prob: 0.87 },
    { team_id: 2, team: "South Korea", projected_points: 5, projected_goals_for: 4, projected_goal_diff: 1, qualification_prob: 0.6 },
    { team_id: 3, team: "Czechia", projected_points: 4, projected_goals_for: 3, projected_goal_diff: 0, qualification_prob: 0.41 },
    { team_id: 4, team: "South Africa", projected_points: 2, projected_goals_for: 2, projected_goal_diff: -4, qualification_prob: 0.12 },
  ];

  it("renders all teams with qualification percentages", () => {
    render(<GroupTable standings={standings} />);
    expect(screen.getByText("87%")).toBeInTheDocument();
    // The Floodlight table is a flex layout carrying ARIA table roles, so the
    // four teams surface as rows beneath the header row.
    expect(screen.getAllByRole("row")).toHaveLength(5);
    for (const team of ["Mexico", "South Korea", "Czechia", "South Africa"]) {
      expect(screen.getByText(team)).toBeInTheDocument();
    }
  });
});
