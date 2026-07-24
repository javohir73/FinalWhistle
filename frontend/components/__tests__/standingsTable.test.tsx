/** StandingsTable: the zone-aware Floodlight table that generalises GroupTable.
 *  Two shapes exercised here — a league table with CL/Europa/relegation zone
 *  stripes + legend, and the WC26 group shape (no zones, Top-2 QualificationBar
 *  column, no legend). */
import { render, screen } from "@testing-library/react";
import { StandingsTable } from "@/components/StandingsTable";
import type { StandingsTableRow } from "@/components/StandingsTable";
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

/** The `role="row"` element wrapping a team's cells, reached from its name
 *  span (a plain `.closest("div")` now lands on the rowheader wrapper). */
const rowFor = (name: string) => screen.getByText(name).closest('[role="row"]');

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

  it("exposes ARIA table semantics so headers associate with cells", () => {
    expect(screen.getByRole("table")).toBeInTheDocument();
    // header row + one row per team.
    expect(screen.getAllByRole("row")).toHaveLength(3);
    expect(screen.getAllByRole("columnheader").map((c) => c.textContent)).toEqual([
      "Team",
      "GD",
      "Pts",
      "Top 2",
    ]);
    // Each team is its row's header, so AT announces it alongside every cell.
    expect(screen.getAllByRole("rowheader")).toHaveLength(2);
  });

  it("labels the qualification bar instead of leaving a bare percentage", () => {
    expect(screen.getByRole("img", { name: "Top 2 chance 87%" })).toBeInTheDocument();
  });
});

describe("NRL ladder shape (club crests, W–L / Diff / Pts / Top-8% columns)", () => {
  // Rows carry the native NRL ladder metrics. `projected_points` is the field
  // the shared Pts column reads (NRL points mapped in), kept alongside the
  // native `points` so the row reads as a real ladder entry.
  const ladderRows: StandingsTableRow[] = [
    { team_id: 1, team: "Storm", wins: 16, losses: 4, diff: 212, points: 34, projected_points: 34, projection_pct: 0.97 },
    { team_id: 2, team: "Panthers", wins: 15, losses: 5, diff: 188, points: 32, projected_points: 32, projection_pct: 0.92 },
    { team_id: 9, team: "Dolphins", wins: 10, losses: 10, diff: -14, points: 22, projected_points: 22, projection_pct: null },
  ];

  beforeEach(() => {
    render(
      <StandingsTable
        standings={ladderRows}
        zones={COMPETITIONS.nrl.zones}
        badge="club"
        teamBasePath="/nrl/team"
        teamHeader="Club"
        columns={["wl", "diff", "pts", "top8"]}
      />,
    );
  });

  it("swaps in the NRL column headers between the club and the numerals", () => {
    expect(screen.getAllByRole("columnheader").map((c) => c.textContent)).toEqual([
      "Club",
      "W–L",
      "Diff",
      "Pts",
      "Top 8%",
    ]);
  });

  it("links a club through to its /nrl/team page", () => {
    expect(screen.getByText("Storm").closest("a")).toHaveAttribute("href", "/nrl/team/1");
  });

  it("stripes the rank-1 club with the finals (lime) tone", () => {
    expect(rowFor("Storm")).toHaveClass("border-l-win");
  });

  it("renders the W–L, Diff and Pts values", () => {
    expect(screen.getByText("16–4")).toBeInTheDocument();
    expect(screen.getByText("+212")).toBeInTheDocument();
    // Pts (34) shares its digits with no other cell on the top row.
    expect(screen.getByText("34")).toBeInTheDocument();
  });

  it("prints the top-8 projection as a rounded percentage", () => {
    expect(screen.getByText("97%")).toBeInTheDocument();
  });

  it("degrades a missing top-8 projection to an em dash", () => {
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
