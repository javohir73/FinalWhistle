/** StandingsTable: the zone-aware Floodlight table that generalises GroupTable.
 *  Two shapes exercised here — a league table with CL/Europa/relegation zone
 *  stripes + legend, and the WC26 group shape (no zones, Top-2 QualificationBar
 *  column, no legend). */
import { render, screen } from "@testing-library/react";
import { StandingsTable } from "@/components/StandingsTable";
import { COMPETITIONS } from "@/lib/sports";
import type { StandingRow } from "@/lib/types";

// The shared European banding (1-4 CL, 5 Europa, 18-20 relegation) that
// epl/laliga/bundesliga carry in the registry.
const EUROPEAN_LEAGUE_ZONES = COMPETITIONS.epl.zones;

/** A full 20-team league table; points/GD taper down the table so the order
 *  reads plausibly, though the component keys zones off row index, not value. */
const leagueTable: StandingRow[] = Array.from({ length: 20 }, (_, i) => ({
  team_id: i + 1,
  team: `Team ${i + 1}`,
  projected_points: 60 - i * 2,
  projected_goals_for: 40 - i,
  projected_goal_diff: 30 - i * 3,
  qualification_prob: null,
}));

/** The row `<div>` wrapping a team's cells, reached from its name span. */
const rowFor = (name: string) => screen.getByText(name).closest("div");

describe("league table with zones", () => {
  beforeEach(() => {
    render(<StandingsTable standings={leagueTable} zones={EUROPEAN_LEAGUE_ZONES} />);
  });

  it("stripes the rank-1 row with the Champions League (lime) tone", () => {
    expect(rowFor("Team 1")).toHaveClass("border-l-win");
  });

  it("stripes a relegation row (rank 19) with the loss (rose) tone", () => {
    expect(rowFor("Team 19")).toHaveClass("border-l-loss");
  });

  it("renders a legend labelling every zone", () => {
    expect(screen.getByText("Champions League")).toBeInTheDocument();
    expect(screen.getByText("Europa League")).toBeInTheDocument();
    expect(screen.getByText("Relegation")).toBeInTheDocument();
  });

  it("links each team name through to its team page", () => {
    expect(screen.getByText("Team 1").closest("a")).toHaveAttribute("href", "/team/1");
  });
});

describe("group shape (no zones, Top-2 qualification column)", () => {
  const group: StandingRow[] = [
    { team_id: 10, team: "Mexico", projected_points: 7, projected_goals_for: 5, projected_goal_diff: 4, qualification_prob: 0.87 },
    { team_id: 20, team: "South Korea", projected_points: 4, projected_goals_for: 3, projected_goal_diff: -1, qualification_prob: 0.31 },
  ];

  beforeEach(() => {
    render(<StandingsTable standings={group} zones={[]} showQualification />);
  });

  it("shows the Top-2 qualification bar with its printed percentage", () => {
    expect(screen.getByText("Top 2")).toBeInTheDocument();
    expect(screen.getByText("87%")).toBeInTheDocument();
  });

  it("renders no zone legend when there are no zones", () => {
    expect(screen.queryByText("Champions League")).not.toBeInTheDocument();
    expect(screen.queryByText("Relegation")).not.toBeInTheDocument();
  });
});
