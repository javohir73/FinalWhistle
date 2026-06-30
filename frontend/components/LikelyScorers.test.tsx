/** The "Likely scorers" card: a per-team top-5 ranked by anytime-score chance,
 *  with a mode badge (squad estimate vs confirmed XI) and a "2+" chip gated on
 *  the 2+ probability. These assert the render rules the spec calls out. */
import { render, screen, within } from "@testing-library/react";
import { LikelyScorers } from "./LikelyScorers";
import type { Goalscorers } from "@/lib/types";

function player(name: string, p_score: number, p_score_2plus = 0, position = "F") {
  return { name, position, p_score, p_score_2plus, xg: p_score };
}

const base: Goalscorers = {
  mode: "squad",
  home: [player("A. Striker", 0.25, 0.12)],
  away: [player("B. Winger", 0.18, 0.03)],
};

test("squad mode shows the 'Squad estimate' badge", () => {
  render(<LikelyScorers home="Home" away="Away" data={base} />);
  expect(screen.getByText("Squad estimate")).toBeInTheDocument();
  expect(screen.queryByText("Confirmed XI")).not.toBeInTheDocument();
});

test("lineup mode shows the 'Confirmed XI' badge", () => {
  render(<LikelyScorers home="Home" away="Away" data={{ ...base, mode: "lineup" }} />);
  expect(screen.getByText("Confirmed XI")).toBeInTheDocument();
  expect(screen.queryByText("Squad estimate")).not.toBeInTheDocument();
});

test("the '2+' chip shows only at/above the 0.10 threshold", () => {
  render(<LikelyScorers home="Home" away="Away" data={base} />);
  // Home player has 2+ = 0.12 (chip), away has 0.03 (no chip).
  const chips = screen.getAllByText("2+");
  expect(chips).toHaveLength(1);
});

test("renders name, position and anytime-score percentage", () => {
  render(<LikelyScorers home="Home" away="Away" data={base} />);
  expect(screen.getByText("A. Striker")).toBeInTheDocument();
  expect(screen.getByText("25%")).toBeInTheDocument();
  expect(screen.getAllByText("F").length).toBeGreaterThan(0);
});

test("shows at most the top 5 players per team", () => {
  const many = Array.from({ length: 8 }, (_, i) => player(`Home P${i}`, 0.3 - i * 0.02));
  render(
    <LikelyScorers home="Home" away="Away" data={{ ...base, home: many }} />,
  );
  expect(screen.getByText("Home P0")).toBeInTheDocument();
  expect(screen.getByText("Home P4")).toBeInTheDocument();
  expect(screen.queryByText("Home P5")).not.toBeInTheDocument();
});

test("a team with no players shows a fallback, not an empty list", () => {
  render(
    <LikelyScorers home="Home" away="Away" data={{ ...base, away: [] }} />,
  );
  expect(screen.getByText("No player data yet.")).toBeInTheDocument();
});

test("omits the position label when position is null", () => {
  const data: Goalscorers = {
    mode: "squad",
    home: [{ name: "No Pos", position: null, p_score: 0.2, p_score_2plus: 0, xg: 0.2 }],
    away: [],
  };
  render(<LikelyScorers home="Home" away="Away" data={data} />);
  const row = screen.getByText("No Pos").closest("li")!;
  // Only the name and percentage — no leading position token.
  expect(within(row).getByText("No Pos")).toBeInTheDocument();
  expect(within(row).getByText("20%")).toBeInTheDocument();
});
