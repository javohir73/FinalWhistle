/** FormationPitch: lays out the starting XI from each player's grid ("row:col"),
 *  renders all eleven shirts, stacks defence→attack (GK at the bottom), and
 *  reveals a player's name + position on tap/Enter (keyboard accessible). */
import { render, screen, fireEvent, within } from "@testing-library/react";
import { FormationPitch, layoutRows } from "@/components/FormationPitch";
import type { LineupPlayer, TeamLineup } from "@/lib/types";

// A canonical 4-3-3: GK (row 1), back four (row 2), midfield three (row 3),
// front three (row 4). cols run left→right within each line.
const start_xi: LineupPlayer[] = [
  { name: "Alisson", number: 1, position: "G", grid: "1:1", is_starter: true },
  { name: "Dani Alves", number: 2, position: "D", grid: "2:4", is_starter: true },
  { name: "Marquinhos", number: 4, position: "D", grid: "2:3", is_starter: true },
  { name: "Thiago Silva", number: 3, position: "D", grid: "2:2", is_starter: true },
  { name: "Alex Sandro", number: 6, position: "D", grid: "2:1", is_starter: true },
  { name: "Casemiro", number: 5, position: "M", grid: "3:3", is_starter: true },
  { name: "Fred", number: 8, position: "M", grid: "3:2", is_starter: true },
  { name: "Paqueta", number: 7, position: "M", grid: "3:1", is_starter: true },
  { name: "Raphinha", number: 11, position: "F", grid: "4:3", is_starter: true },
  { name: "Richarlison", number: 9, position: "F", grid: "4:2", is_starter: true },
  { name: "Vinicius Junior", number: 10, position: "F", grid: "4:1", is_starter: true },
];

const lineup: TeamLineup = {
  team: "Brazil",
  formation: "4-3-3",
  coach: "Tite",
  start_xi,
  bench: [],
};

describe("FormationPitch", () => {
  it("renders all eleven starters as shirt buttons", () => {
    render(<FormationPitch lineup={lineup} />);
    const shirts = screen.getAllByRole("button");
    expect(shirts).toHaveLength(11);
    // Each shirt's accessible name carries the number, name and position.
    expect(
      screen.getByRole("button", { name: /#10 Vinicius Junior \(F\)/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /#1 Alisson \(G\)/ })).toBeInTheDocument();
  });

  it("shows the team name and formation", () => {
    render(<FormationPitch lineup={lineup} />);
    expect(screen.getByText("Brazil")).toBeInTheDocument();
    expect(screen.getByText("4-3-3")).toBeInTheDocument();
    expect(screen.getByText(/Tite/)).toBeInTheDocument();
  });

  it("shows player names by default (not sr-only) and toggles detail on tap", () => {
    render(<FormationPitch lineup={lineup} />);
    const vini = screen.getByRole("button", { name: /Vinicius Junior/ });
    const cell = vini.parentElement as HTMLElement;

    // The name is visible without tapping (team-details Last XI shows names).
    const nameEl = within(cell).getByText("Junior");
    expect(nameEl).toBeVisible();
    expect(nameEl.className).not.toContain("sr-only");

    // Tapping toggles the pressed state (reveals the position line).
    expect(vini).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(vini);
    expect(vini).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(vini);
    expect(vini).toHaveAttribute("aria-pressed", "false");
  });

  it("exposes an accessible group label for the XI", () => {
    render(<FormationPitch lineup={lineup} />);
    expect(
      screen.getByRole("group", { name: /Brazil starting eleven, 4-3-3/ }),
    ).toBeInTheDocument();
  });
});

describe("layoutRows", () => {
  it("groups by grid row, orders each line left→right, and stacks attack→defence", () => {
    const rows = layoutRows(start_xi);
    // 4 lines: forwards, midfield, defence, GK (emitted attack-first so the GK
    // renders at the bottom of the column).
    expect(rows).toHaveLength(4);
    expect(rows[0].map((p) => p.name)).toEqual([
      "Vinicius Junior", // 4:1
      "Richarlison", // 4:2
      "Raphinha", // 4:3
    ]);
    // Last emitted line is the GK line (row 1) → rendered at the bottom.
    expect(rows[rows.length - 1].map((p) => p.name)).toEqual(["Alisson"]);
    // Every starter is placed.
    expect(rows.flat()).toHaveLength(11);
  });

  it("falls back to grouping by position when the provider gives no grid", () => {
    // API-Football often returns null grids; the XI must still form lines by
    // position rather than collapsing into one packed row.
    const players: LineupPlayer[] = [
      { name: "Keeper", number: 1, position: "G", grid: null, is_starter: true },
      { name: "Back", number: 2, position: "D", grid: null, is_starter: true },
      { name: "Mid", number: 8, position: "M", grid: null, is_starter: true },
      { name: "Striker", number: 9, position: "F", grid: null, is_starter: true },
      { name: "Mystery", number: 99, position: null, grid: null, is_starter: true },
    ];
    const rows = layoutRows(players); // attackingUp default → GK at the bottom
    expect(rows.flat()).toHaveLength(5); // nobody dropped
    expect(rows.length).toBeGreaterThanOrEqual(4); // distinct position lines, not one row
    // GK line renders last (bottom of the column).
    expect(rows[rows.length - 1].map((p) => p.name)).toEqual(["Keeper"]);
    // Unknown-position player sits at the attacking end (first line here).
    expect(rows[0].map((p) => p.name)).toContain("Mystery");
  });

  it("still uses the grid when every player is positioned across ≥2 lines", () => {
    const rows = layoutRows(start_xi);
    expect(rows).toHaveLength(4); // 4-3-3 → four grid lines
  });
});
