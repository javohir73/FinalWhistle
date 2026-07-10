import { render, screen } from "@testing-library/react";
import { LadderTable } from "@/components/LadderTable";
import type { LadderRow } from "@/lib/types";

const rows: LadderRow[] = [
  { rank: 1, team_id: 12, name: "Panthers", played: 16, wins: 13, draws: 0, losses: 3, points: 26, diff: 280 },
  { rank: 9, team_id: 13, name: "Rabbitohs", played: 15, wins: 8, draws: 0, losses: 7, points: 16, diff: 84 },
];

it("links each club to its profile page", () => {
  render(<LadderTable rows={rows} />);
  expect(screen.getByRole("link", { name: /Panthers/ })).toHaveAttribute(
    "href", "/nrl/team/12",
  );
  expect(screen.getByRole("link", { name: /Rabbitohs/ })).toHaveAttribute(
    "href", "/nrl/team/13",
  );
});

it("shows Top 8%/Top 4% columns when projections are provided", () => {
  render(
    <LadderTable
      rows={rows}
      projections={{ Panthers: { top8: 0.97, top4: 0.55 }, Rabbitohs: { top8: 0.62, top4: 0.1 } }}
    />,
  );
  expect(screen.getByText("Top 8%")).toBeInTheDocument();
  expect(screen.getByText("97%")).toBeInTheDocument();
  expect(screen.getByText("55%")).toBeInTheDocument();
});

it("hides the projections columns when the projections table is empty", () => {
  render(<LadderTable rows={rows} projections={{}} />);
  expect(screen.queryByText("Top 8%")).not.toBeInTheDocument();
});

it("hides the projections columns when no projections prop is passed", () => {
  render(<LadderTable rows={rows} />);
  expect(screen.queryByText("Top 8%")).not.toBeInTheDocument();
});
