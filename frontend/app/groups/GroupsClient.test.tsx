/** Groups listing — D1 (league pivot, docs/LEAGUE-PIVOT-PLAN.md): a
 *  format: "league" tournament with a single Group renders as one full-width
 *  table titled with the tournament's name, not the WC26 multi-group grid.
 *  Real api.ts fetches are left unmocked (as in bracketsClient.test.tsx) —
 *  they reject harmlessly in jsdom; only the SSR-supplied `initialGroups` and
 *  `tournament` props are asserted on. */
import { render, screen } from "@testing-library/react";
import { GroupsClient } from "./GroupsClient";
import type { ActiveTournament, Group } from "@/lib/types";

const WC26: ActiveTournament = {
  id: 0,
  name: "World Cup 2026",
  year: 2026,
  format: "knockout",
  has_brackets: true,
};

const LEAGUE: ActiveTournament = {
  id: 1,
  name: "Premier League 2026-27",
  year: 2026,
  format: "league",
  has_brackets: false,
};

const groupA: Group = {
  id: 1,
  name: "Group A",
  standings: [
    { team_id: 1, team: "Mexico", projected_points: 6, projected_goals_for: 5, projected_goal_diff: 3, qualification_prob: 0.87 },
  ],
};
const groupB: Group = {
  id: 2,
  name: "Group B",
  standings: [
    { team_id: 2, team: "Japan", projected_points: 4, projected_goals_for: 3, projected_goal_diff: 1, qualification_prob: 0.4 },
  ],
};
const leagueTable: Group = {
  id: 1,
  name: "Premier League",
  standings: [
    { team_id: 1, team: "Arsenal", projected_points: 6, projected_goals_for: 5, projected_goal_diff: 3, qualification_prob: 0.2 },
    { team_id: 2, team: "Coventry City", projected_points: 3, projected_goals_for: 2, projected_goal_diff: -1, qualification_prob: 0.01 },
  ],
};

it("renders the WC26 multi-group card grid unchanged", () => {
  render(<GroupsClient initialGroups={[groupA, groupB]} tournament={WC26} />);
  expect(screen.getByRole("heading", { name: /Group tables/ })).toBeInTheDocument();
  expect(screen.getByText("Group A")).toBeInTheDocument();
  expect(screen.getByText("Group B")).toBeInTheDocument();
  // The card grid's own "View matches" links, not a single full-width table.
  expect(screen.getAllByText("View matches").length).toBe(2);
});

it("renders a single full-width league table titled with the tournament name", () => {
  render(<GroupsClient initialGroups={[leagueTable]} tournament={LEAGUE} />);
  expect(screen.getByRole("heading", { name: "Premier League 2026-27" })).toBeInTheDocument();
  expect(screen.getByText("Arsenal")).toBeInTheDocument();
  expect(screen.getByText("Coventry City")).toBeInTheDocument();
  expect(screen.queryByText("View matches")).not.toBeInTheDocument();
  // League mode drops the WC-specific Top-2 qualification column — "top two"
  // is not a real finish line in a 20-team league (GroupTable mode="league").
  expect(screen.queryByText("Top 2")).not.toBeInTheDocument();
});

it("falls back to the card grid if a league tournament somehow has more than one group", () => {
  render(<GroupsClient initialGroups={[groupA, groupB]} tournament={LEAGUE} />);
  expect(screen.getByRole("heading", { name: /Group tables/ })).toBeInTheDocument();
  expect(screen.getAllByText("View matches").length).toBe(2);
});
