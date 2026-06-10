/** UserPredictionCard: picking a side reveals the you-vs-AI comparison and a
 *  human verdict. */
import { render, screen, fireEvent } from "@testing-library/react";
import { UserPredictionCard } from "@/components/UserPredictionCard";
import type { MatchSummary } from "@/lib/types";

function match(): MatchSummary {
  return {
    match_id: 7, stage: "group", group: "C", kickoff_utc: null,
    venue: null, venue_city: null, venue_country: null, is_neutral: true,
    status: "scheduled", score_home: null, score_away: null, minute: null,
    teams: { home: "Brazil", away: "Scotland" },
    predicted_winner: "Brazil",
    probabilities: { home_win: 0.62, draw: 0.24, away_win: 0.14 },
    predicted_score: { home: 2, away: 0, probability: 0.1 },
    confidence: "High",
  };
}

it("calls onPick and shows the AI comparison when a side is chosen", () => {
  const onPick = jest.fn();
  const { rerender } = render(
    <UserPredictionCard match={match()} country="Brazil" pick={undefined} onPick={onPick} tz="UTC" />,
  );

  // Country option uses the team name; Brazil is the home side here.
  fireEvent.click(screen.getByRole("button", { name: "Brazil" }));
  expect(onPick).toHaveBeenCalledWith("home");

  // With the pick applied, the comparison + agreement verdict appear (AI also leans home).
  rerender(
    <UserPredictionCard match={match()} country="Brazil" pick="home" onPick={onPick} tz="UTC" />,
  );
  expect(screen.getByText("You agree with the AI")).toBeInTheDocument();
});

it("flags an upset when the user backs the long shot", () => {
  render(
    <UserPredictionCard match={match()} country="Brazil" pick="away" onPick={jest.fn()} tz="UTC" />,
  );
  expect(screen.getByText("You’re calling an upset")).toBeInTheDocument();
});
