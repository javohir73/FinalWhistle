/** TimelineSpine (Floodlight P2 slice p2-s3): the fixtures list falls down a
 *  per-day vertical spine, each kickoff hanging off it as a compact MatchCard
 *  with a dot on the spine -- rose (`border-loss`) when live, hairline
 *  (`border-border`) otherwise. */
import { render, screen } from "@testing-library/react";
import { TimelineSpine } from "@/components/TimelineSpine";
import type { MatchSummary } from "@/lib/types";

function makeMatch(
  id: number,
  home: string,
  away: string,
  overrides: Partial<MatchSummary> = {},
): MatchSummary {
  return {
    match_id: id,
    stage: "group",
    group: "Group A",
    kickoff_utc: "2026-06-14T18:00:00+00:00",
    venue: "Lumen Field",
    venue_city: "Seattle",
    venue_country: "USA",
    is_neutral: true,
    status: "scheduled",
    score_home: null,
    score_away: null,
    minute: null,
    period: null,
    injury_time: null,
    penalty_home: null,
    penalty_away: null,
    teams: { home, away },
    predicted_winner: home,
    probabilities: { home_win: 0.6, draw: 0.25, away_win: 0.15 },
    predicted_score: { home: 2, away: 1, probability: 0.1 },
    confidence: "Medium",
    goal_events: [],
    ...overrides,
  };
}

// A live match: in_play with a recent kickoff so isLiveNow() reads it as live.
const liveMatch = makeMatch(1, "Brazil", "Scotland", {
  status: "in_play",
  minute: 34,
  period: "first_half",
  kickoff_utc: new Date(Date.now() - 30 * 60_000).toISOString(),
});
const upcomingMatch = makeMatch(2, "Spain", "Uruguay");

const days = [
  { key: "d1", heading: "Matchday 1", matches: [liveMatch] },
  { key: "d2", heading: "Matchday 2", matches: [upcomingMatch] },
];

it("renders each day heading and every match's team names", () => {
  render(<TimelineSpine days={days} tz="UTC" />);

  expect(screen.getByText("Matchday 1")).toBeInTheDocument();
  expect(screen.getByText("Matchday 2")).toBeInTheDocument();

  expect(screen.getByText(/Brazil/)).toBeInTheDocument();
  expect(screen.getByText(/Scotland/)).toBeInTheDocument();
  expect(screen.getByText(/Spain/)).toBeInTheDocument();
  expect(screen.getByText(/Uruguay/)).toBeInTheDocument();
});

it("marks a live row's spine dot with border-loss and an upcoming row's with border-border", () => {
  render(<TimelineSpine days={days} tz="UTC" />);

  const liveRow = screen.getByText(/Brazil/).closest(".relative")!;
  const liveDot = liveRow.querySelector(":scope > span");
  expect(liveDot).toHaveClass("border-loss");
  expect(liveDot).not.toHaveClass("border-border");

  const upcomingRow = screen.getByText(/Spain/).closest(".relative")!;
  const upcomingDot = upcomingRow.querySelector(":scope > span");
  expect(upcomingDot).toHaveClass("border-border");
  expect(upcomingDot).not.toHaveClass("border-loss");
});
