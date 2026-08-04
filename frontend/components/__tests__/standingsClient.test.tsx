/** StandingsClient's pre-draw honesty: a league-format competition ships its
 *  table group before the draw (the UCL league phase all summer), and zero
 *  rows must read as "no draw yet" — not as a broken bare table under a
 *  subtitle claiming live updates. */
import { render, screen } from "@testing-library/react";
import { StandingsClient } from "@/components/StandingsClient";
import { getGroups } from "@/lib/api";
import type { ActiveTournament, Group, StandingRow } from "@/lib/types";

jest.mock("@/lib/api");
const mockGroups = getGroups as jest.MockedFunction<typeof getGroups>;

const ucl: ActiveTournament = {
  id: 5,
  name: "UEFA Champions League 2026-27",
  year: 2026,
  format: "league",
  has_brackets: false,
};

const row = (over: Partial<StandingRow> = {}): StandingRow => ({
  team_id: 1,
  team: "Arsenal",
  projected_points: 9,
  projected_goals_for: 7,
  projected_goal_diff: 5,
  qualification_prob: 0.92,
  ...over,
});

afterEach(() => jest.resetAllMocks());

it("renders an honest pre-draw state instead of a bare table when the group has no rows", async () => {
  const empty: Group[] = [{ id: 16, name: "Champions League", standings: [] }];
  mockGroups.mockResolvedValue(empty);
  render(<StandingsClient comp="ucl" initialGroups={empty} tournament={ucl} />);

  expect(
    await screen.findByText(/fills in once the UEFA Champions League draw is made/),
  ).toBeInTheDocument();
  expect(
    screen.getByText("The table appears here once the draw is made and fixtures load."),
  ).toBeInTheDocument();
  // No bare column header, no orphan zone legend, no live-updates claim.
  expect(screen.queryByRole("columnheader")).toBeNull();
  expect(screen.queryByText("Round of 16")).toBeNull();
  expect(screen.queryByText(/Live standings/)).toBeNull();
});

it("renders the table and the live subtitle once rows exist", async () => {
  const groups: Group[] = [{ id: 16, name: "Champions League", standings: [row()] }];
  mockGroups.mockResolvedValue(groups);
  render(<StandingsClient comp="ucl" initialGroups={groups} tournament={ucl} />);

  expect(await screen.findByText("Arsenal")).toBeInTheDocument();
  expect(
    screen.getByText("Live standings, updated as results come in."),
  ).toBeInTheDocument();
});
