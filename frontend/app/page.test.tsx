/** Home dashboard tests (task 6.9). */
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import HomePage from "./page";
import { getUpcomingMatches } from "@/lib/api";
import type { MatchSummary } from "@/lib/types";

jest.mock("@/lib/api");
const mockGet = getUpcomingMatches as jest.MockedFunction<typeof getUpcomingMatches>;

function match(id: number, home: string, away: string, group: string): MatchSummary {
  return {
    match_id: id, stage: "group", group, kickoff_utc: null, is_neutral: true,
    teams: { home, away },
    predicted_winner: home,
    probabilities: { home_win: 0.6, draw: 0.25, away_win: 0.15 },
    predicted_score: { home: 2, away: 1, probability: 0.1 },
    confidence: "Medium",
  };
}

afterEach(() => jest.resetAllMocks());

it("shows loading then the match cards", async () => {
  mockGet.mockResolvedValue([match(1, "Brazil", "Scotland", "Group C")]);
  render(<HomePage />);
  expect(screen.getByRole("status")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText("Scotland")).toBeInTheDocument());
});

it("shows an error state when the API fails", async () => {
  mockGet.mockRejectedValue(new Error("boom"));
  render(<HomePage />);
  await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
});

it("filters matches by team search", async () => {
  mockGet.mockResolvedValue([
    match(1, "Brazil", "Scotland", "Group C"),
    match(2, "Spain", "Uruguay", "Group H"),
  ]);
  render(<HomePage />);
  await waitFor(() => expect(screen.getByText("Scotland")).toBeInTheDocument());

  fireEvent.change(screen.getByLabelText("Search team"), { target: { value: "spain" } });
  expect(screen.queryByText("Scotland")).not.toBeInTheDocument();
  expect(screen.getByText("Uruguay")).toBeInTheDocument();
});
