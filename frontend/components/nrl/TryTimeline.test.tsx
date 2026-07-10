import { render, screen } from "@testing-library/react";
import { TryTimeline } from "./TryTimeline";
import type { NrlTryEventOut } from "@/lib/types";

const events: NrlTryEventOut[] = [
  { minute: 7, team: "Knights", player: "K. Ponga", score_home: 6, score_away: 0 },
  { minute: 23, team: "Cowboys", player: "S. Drinkwater", score_home: 6, score_away: 6 },
];

test("renders each try with minute, player and running score", () => {
  render(<TryTimeline events={events} homeTeam="Knights" awayTeam="Cowboys" />);
  expect(screen.getByText("7'")).toBeInTheDocument();
  expect(screen.getByText("K. Ponga")).toBeInTheDocument();
  expect(screen.getByText("6–0")).toBeInTheDocument();
  expect(screen.getByText("6–6")).toBeInTheDocument();
});

test("empty timeline renders the no-tries note", () => {
  render(<TryTimeline events={[]} homeTeam="Knights" awayTeam="Cowboys" />);
  expect(screen.getByText(/no tries recorded/i)).toBeInTheDocument();
});
