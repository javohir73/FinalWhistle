import { render, screen } from "@testing-library/react";
import { VenueSplits } from "./VenueSplits";
import type { NrlVenueSplit } from "@/lib/types";

const splits: NrlVenueSplit[] = [
  { venue: "Leichhardt Oval", played: 2, wins: 2, draws: 0, losses: 0,
    avg_for: 39.0, avg_against: 11.0 },
  { venue: "Accor Stadium", played: 1, wins: 0, draws: 0, losses: 1,
    avg_for: 12.0, avg_against: 30.0 },
];

test("renders one row per venue with record and averages", () => {
  render(<VenueSplits splits={splits} />);
  expect(screen.getByText("Leichhardt Oval")).toBeInTheDocument();
  expect(screen.getByText("2-0-0")).toBeInTheDocument();
  expect(screen.getByText("39.0 for / 11.0 against")).toBeInTheDocument();
  expect(screen.getByText("Accor Stadium")).toBeInTheDocument();
});

test("empty splits renders nothing", () => {
  const { container } = render(<VenueSplits splits={[]} />);
  expect(container.firstChild).toBeNull();
});
