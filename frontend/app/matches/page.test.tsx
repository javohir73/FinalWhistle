/** Matches dashboard tests. */
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
// The route's page.tsx is now a server component; the interactive UI lives in the
// client island. Render that directly (unseeded → it fetches via the mock below).
import { MatchesClient as MatchesPage } from "./MatchesClient";
import { getUpcomingMatches, getHealth } from "@/lib/api";
import type { MatchSummary } from "@/lib/types";

jest.mock("@/lib/api");
const mockGet = getUpcomingMatches as jest.MockedFunction<typeof getUpcomingMatches>;
const mockHealth = getHealth as jest.MockedFunction<typeof getHealth>;

beforeEach(() => {
  // The live-status badge fetches health; keep it resolved so it never crashes.
  mockHealth.mockResolvedValue({
    status: "ok", app: "FinalWhistle", model_version: "poisson-elo-v0.1", live_updates: "inactive",
  });
});

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
    status: "scheduled", score_home: null, score_away: null, minute: null,
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

it("remembers 'Show all matches' across remounts (back from a match page)", async () => {
  localStorage.setItem(
    "finalwhistle:selected-country:v1",
    JSON.stringify({ team_id: 1, team: "Brazil", selected_at: "2026-06-01T00:00:00Z", prediction_revealed: true }),
  );
  mockGet.mockResolvedValue([
    match(1, "Brazil", "Scotland", "Group C"),
    match(2, "Spain", "Uruguay", "Group H"),
  ]);

  // First visit: focused on Brazil → flip to all matches.
  const first = render(<MatchesPage />);
  await waitFor(() => expect(screen.getByText("Scotland")).toBeInTheDocument());
  expect(screen.queryByText("Uruguay")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Show all matches" }));
  expect(screen.getByText("Uruguay")).toBeInTheDocument();
  first.unmount();

  // Remount (user opened a match and came back): still showing all matches.
  render(<MatchesPage />);
  await waitFor(() => expect(screen.getByText("Uruguay")).toBeInTheDocument());

  localStorage.removeItem("finalwhistle:selected-country:v1");
  sessionStorage.clear();
});

it("offers a location/timezone control", async () => {
  mockGet.mockResolvedValue([match(1, "Brazil", "Scotland", "Group C")]);
  render(<MatchesPage />);
  await waitFor(() => expect(screen.getByText("Scotland")).toBeInTheDocument());
  expect(screen.getByLabelText("Choose your timezone")).toBeInTheDocument();
});
