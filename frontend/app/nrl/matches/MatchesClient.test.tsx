import { act, fireEvent, render, screen } from "@testing-library/react";
import { MatchesClient } from "./MatchesClient";
import { getNrlMatches } from "@/lib/api";
import type { NrlMatchesResponse } from "@/lib/types";

jest.mock("@/lib/api", () => ({ getNrlMatches: jest.fn() }));

const mins = (n: number) => new Date(Date.now() + n * 60_000).toISOString();

const fixtures: NrlMatchesResponse = {
  season: 2026,
  disclaimer: "d",
  rounds: [
    { round: 19, matches: [
      { id: 1, match_no: 1, kickoff_utc: mins(-3 * 24 * 60), venue: null, home: "Dolphins", away: "Sharks",
        home_team_id: 1, away_team_id: 2, score_home: 0, score_away: 66, status: "finished", prediction: null },
    ]},
    { round: 20, matches: [
      { id: 2, match_no: 2, kickoff_utc: mins(-30), venue: null, home: "Panthers", away: "Broncos",
        home_team_id: 3, away_team_id: 4, score_home: 12, score_away: 6, status: "scheduled", prediction: null },
      { id: 3, match_no: 3, kickoff_utc: mins(60 * 24), venue: null, home: "Raiders", away: "Rabbitohs",
        home_team_id: 5, away_team_id: 6, score_home: null, score_away: null, status: "scheduled", prediction: null },
    ]},
  ],
};

beforeEach(() => {
  jest.clearAllMocks();
  // Keep background refreshes pending unless a test specifically resolves one;
  // this mirrors an in-flight request and avoids post-assertion state updates.
  (getNrlMatches as jest.Mock).mockReturnValue(new Promise(() => {}));
});

it("defaults to Upcoming with the live strip pinned on top", () => {
  render(<MatchesClient initial={fixtures} />);
  expect(getNrlMatches).toHaveBeenCalledTimes(1); // no 60s wait before the first refresh
  expect(screen.getByText(/live now/i)).toBeInTheDocument();        // pinned strip label
  // Compact MatchCards collapse both sides onto one name line, so match a
  // substring rather than an exact team-name node.
  expect(screen.getByText(/Panthers/)).toBeInTheDocument();         // live match in strip
  expect(screen.getByText(/Raiders/)).toBeInTheDocument();          // upcoming below
  expect(screen.queryByText(/Dolphins/)).not.toBeInTheDocument();   // finished hidden
  // The spine keeps the round structure as its day heading...
  expect(screen.getByText("Round 20")).toBeInTheDocument();
  // ...and each fixture links to its (season, round, match_no) detail page.
  expect(screen.getByText(/Raiders/).closest("a")).toHaveAttribute(
    "href",
    "/nrl/match/2026/20/3",
  );
});

it("Finished tab shows results, latest round first, and hides live", () => {
  render(<MatchesClient initial={fixtures} />);
  fireEvent.click(screen.getByRole("tab", { name: "Finished" }));
  expect(screen.getByText(/Dolphins/)).toBeInTheDocument();
  expect(screen.queryByText(/Panthers/)).not.toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Finished" })).toHaveAttribute("aria-selected", "true");
});

it("Live tab shows only in-window matches", () => {
  render(<MatchesClient initial={fixtures} />);
  fireEvent.click(screen.getByRole("tab", { name: "Live" }));
  expect(screen.getByText(/Panthers/)).toBeInTheDocument();
  expect(screen.queryByText(/Raiders/)).not.toBeInTheDocument();
});

it("shows the per-tab empty state", () => {
  render(<MatchesClient initial={{ ...fixtures, rounds: [] }} />);
  expect(screen.getByText("No upcoming fixtures yet.")).toBeInTheDocument();
  expect(getNrlMatches).toHaveBeenCalledTimes(1); // stale SSR data refreshes even with no live game
});

it("self-promotes a match into the live strip at kickoff, from the clock tick alone", () => {
  jest.useFakeTimers();
  const soon: NrlMatchesResponse = {
    season: 2026,
    disclaimer: "d",
    rounds: [
      { round: 21, matches: [
        { id: 4, match_no: 4, kickoff_utc: mins(2), venue: null, home: "Storm", away: "Eels",
          home_team_id: 7, away_team_id: 8, score_home: null, score_away: null, status: "scheduled", prediction: null },
      ]},
    ],
  };
  render(<MatchesClient initial={soon} />);
  expect(screen.queryByText(/live now/i)).not.toBeInTheDocument();

  act(() => {
    jest.advanceTimersByTime(3 * 60_000); // past kickoff — only the 30s clock tick drives this
  });

  expect(screen.getByText(/live now/i)).toBeInTheDocument();

  jest.useRealTimers();
});
