/** Matches dashboard tests. */
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import MatchesPage from "./page";
import { getUpcomingMatches } from "@/lib/api";
import type { MatchSummary } from "@/lib/types";

jest.mock("@/lib/api");
const mockGet = getUpcomingMatches as jest.MockedFunction<typeof getUpcomingMatches>;

function match(
  id: number,
  home: string,
  away: string,
  group: string,
  extra: Partial<MatchSummary> = {},
): MatchSummary {
  return {
    match_id: id, stage: "group", group, kickoff_utc: null,
    venue: null, venue_city: null, venue_country: null, is_neutral: true,
    teams: { home, away },
    predicted_winner: home,
    probabilities: { home_win: 0.6, draw: 0.25, away_win: 0.15 },
    predicted_score: { home: 2, away: 1, probability: 0.1 },
    confidence: "Medium",
    ...extra,
  };
}

afterEach(() => jest.resetAllMocks());

it("shows loading then the match cards", async () => {
  mockGet.mockResolvedValue([match(1, "Brazil", "Scotland", "Group C")]);
  render(<MatchesPage />);
  expect(screen.getByRole("status")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText("Scotland")).toBeInTheDocument());
});

it("shows an error state when the API fails", async () => {
  mockGet.mockRejectedValue(new Error("boom"));
  render(<MatchesPage />);
  await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
});

it("filters matches by team search", async () => {
  mockGet.mockResolvedValue([
    match(1, "Brazil", "Scotland", "Group C"),
    match(2, "Spain", "Uruguay", "Group H"),
  ]);
  render(<MatchesPage />);
  await waitFor(() => expect(screen.getByText("Scotland")).toBeInTheDocument());

  fireEvent.change(screen.getByLabelText("Search team"), { target: { value: "spain" } });
  expect(screen.queryByText("Scotland")).not.toBeInTheDocument();
  expect(screen.getByText("Uruguay")).toBeInTheDocument();
});

it("groups matches by date and shows venue + a day heading", async () => {
  mockGet.mockResolvedValue([
    match(1, "Mexico", "South Africa", "Group A", {
      kickoff_utc: "2026-06-11T19:00:00+00:00",
      venue: "Estadio Azteca",
      venue_city: "Mexico City",
      venue_country: "Mexico",
    }),
  ]);
  render(<MatchesPage />);
  await waitFor(() => expect(screen.getByText(/Estadio Azteca/)).toBeInTheDocument());
  // A day heading derived from the kickoff date should appear.
  expect(screen.getByText(/2026/)).toBeInTheDocument();
});

it("offers a location/timezone control", async () => {
  mockGet.mockResolvedValue([match(1, "Brazil", "Scotland", "Group C")]);
  render(<MatchesPage />);
  await waitFor(() => expect(screen.getByText("Scotland")).toBeInTheDocument());
  expect(screen.getByLabelText("Choose your timezone")).toBeInTheDocument();
});
