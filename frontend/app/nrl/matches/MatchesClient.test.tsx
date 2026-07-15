import { fireEvent, render, screen } from "@testing-library/react";
import { MatchesClient } from "./MatchesClient";
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

it("defaults to Upcoming with the live strip pinned on top", () => {
  render(<MatchesClient initial={fixtures} />);
  expect(screen.getByText(/live now/i)).toBeInTheDocument();       // pinned strip label
  expect(screen.getByText("Panthers")).toBeInTheDocument();        // live match in strip
  expect(screen.getByText("Raiders")).toBeInTheDocument();         // upcoming below
  expect(screen.queryByText("Dolphins")).not.toBeInTheDocument();  // finished hidden
});

it("Finished tab shows results, latest round first, and hides live", () => {
  render(<MatchesClient initial={fixtures} />);
  fireEvent.click(screen.getByRole("button", { name: "Finished" }));
  expect(screen.getByText("Dolphins")).toBeInTheDocument();
  expect(screen.queryByText("Panthers")).not.toBeInTheDocument();
});

it("Live tab shows only in-window matches", () => {
  render(<MatchesClient initial={fixtures} />);
  fireEvent.click(screen.getByRole("button", { name: "Live" }));
  expect(screen.getByText("Panthers")).toBeInTheDocument();
  expect(screen.queryByText("Raiders")).not.toBeInTheDocument();
});

it("shows the per-tab empty state", () => {
  render(<MatchesClient initial={{ ...fixtures, rounds: [] }} />);
  expect(screen.getByText("No upcoming fixtures yet.")).toBeInTheDocument();
});
