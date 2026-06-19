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
  // Kept resolved for any incidental health fetch; harmless for this surface.
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
    period: null, injury_time: null, penalty_home: null, penalty_away: null,
    teams: { home, away },
    predicted_winner: home,
    probabilities: { home_win: 0.6, draw: 0.25, away_win: 0.15 },
    predicted_score: { home: 2, away: 1, probability: 0.1 },
    confidence: "Medium",
    goal_events: [],
    ...extra,
  };
}

afterEach(() => {
  jest.resetAllMocks();
});

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

it("groups matches by date under a day heading", async () => {
  mockGet.mockResolvedValue([
    match(1, "Mexico", "South Africa", "Group A", {
      kickoff_utc: "2026-06-11T19:00:00+00:00",
      venue: "Estadio Azteca",
      venue_city: "Mexico City",
      venue_country: "Mexico",
    }),
  ]);
  render(<MatchesPage />);
  await waitFor(() => expect(screen.getByText("South Africa")).toBeInTheDocument());
  // A day heading derived from the kickoff date should appear (year included).
  expect(screen.getByText(/2026/)).toBeInTheDocument();
});

it("pins live (in-play) matches in a 'Live now' section at the top", async () => {
  mockGet.mockResolvedValue([
    match(1, "Brazil", "Morocco", "Group C", {
      status: "in_play", period: "second_half", minute: 70,
      // Recent kickoff so isLiveNow() pins it as live (a stale in_play would not).
      score_home: 1, score_away: 1, kickoff_utc: new Date(Date.now() - 60 * 60_000).toISOString(),
    }),
    match(2, "Spain", "Uruguay", "Group H", { kickoff_utc: "2026-06-20T18:00:00+00:00" }),
  ]);
  render(<MatchesPage />);
  await waitFor(() => expect(screen.getByText("Live now")).toBeInTheDocument());

  // The live match is surfaced, and the "Live now" heading precedes the
  // scheduled match in the DOM (pinned to the top, not buried by kickoff order).
  const live = screen.getByText("Live now");
  const scheduledTeam = screen.getByText("Uruguay");
  expect(live.compareDocumentPosition(scheduledTeam) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it("offers a location chip linking to the You hub", async () => {
  mockGet.mockResolvedValue([match(1, "Brazil", "Scotland", "Group C")]);
  render(<MatchesPage />);
  await waitFor(() => expect(screen.getByText("Scotland")).toBeInTheDocument());
  // The big timezone card is gone; a compact location chip links to the You hub.
  // Its label is the viewer's timezone city, which varies by environment, so
  // select it by destination rather than by name.
  const links = screen.getAllByRole("link");
  const chip = links.find((el) => el.getAttribute("href") === "/leaderboard");
  expect(chip).toBeTruthy();
});

it("shows an empty state when a search matches nothing, and recovers on clear", async () => {
  mockGet.mockResolvedValue([
    match(1, "Brazil", "Scotland", "Group C"),
    match(2, "Spain", "Uruguay", "Group H"),
  ]);
  render(<MatchesPage />);
  await waitFor(() => expect(screen.getByText("Scotland")).toBeInTheDocument());

  // Search for something no team matches → the empty state appears.
  fireEvent.change(screen.getByLabelText("Search team"), { target: { value: "zzz" } });
  expect(screen.getByText("No fixtures here yet.")).toBeInTheDocument();

  // Clearing the search restores the fixtures.
  fireEvent.change(screen.getByLabelText("Search team"), { target: { value: "" } });
  expect(screen.getByText("Scotland")).toBeInTheDocument();
  expect(screen.getByText("Uruguay")).toBeInTheDocument();
});

// A finished match has been played; a scheduled one has not. Kickoffs are relative
// so the partition is decided by status, not the wall clock at test time.
const futureKickoff = new Date(Date.now() + 5 * 86_400_000).toISOString();
const pastKickoff = new Date(Date.now() - 2 * 86_400_000).toISOString();

it("shows every fixture under All, and only full-time ones under Finished", async () => {
  mockGet.mockResolvedValue([
    match(1, "Mexico", "South Africa", "Group A", { kickoff_utc: futureKickoff }),
    match(2, "Qatar", "Switzerland", "Group B", {
      status: "finished", score_home: 1, score_away: 1, kickoff_utc: pastKickoff,
    }),
  ]);
  render(<MatchesPage />);
  // Query away-team names: the home team doubles as the predicted winner.
  await waitFor(() => expect(screen.getByText("South Africa")).toBeInTheDocument());

  // Default (All) shows both the upcoming and the finished match.
  expect(screen.getByText("South Africa")).toBeInTheDocument();
  expect(screen.getByText("Switzerland")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "All" })).toHaveAttribute("aria-selected", "true");

  // Switching to Finished keeps the played one and drops the upcoming.
  fireEvent.click(screen.getByRole("tab", { name: "Finished" }));
  expect(screen.getByText("Switzerland")).toBeInTheDocument();
  expect(screen.queryByText("South Africa")).not.toBeInTheDocument();
});

it("narrows to in-play games under the Live filter", async () => {
  mockGet.mockResolvedValue([
    match(1, "Brazil", "Morocco", "Group C", {
      status: "in_play", period: "second_half", minute: 70, score_home: 1, score_away: 1,
      kickoff_utc: new Date(Date.now() - 60 * 60_000).toISOString(),
    }),
    match(2, "Qatar", "Switzerland", "Group B", {
      status: "finished", score_home: 1, score_away: 1, kickoff_utc: pastKickoff,
    }),
  ]);
  render(<MatchesPage />);
  await waitFor(() => expect(screen.getByText("Live now")).toBeInTheDocument());

  fireEvent.click(screen.getByRole("tab", { name: "Live" }));
  // Only the live match remains; the finished one is filtered out.
  expect(screen.getByText("Live now")).toBeInTheDocument();
  expect(screen.getByText("Morocco")).toBeInTheDocument(); // away team of the live match
  expect(screen.queryByText("Switzerland")).not.toBeInTheDocument();
});

it("keeps the live match pinned when switching to the Today filter", async () => {
  mockGet.mockResolvedValue([
    match(1, "Brazil", "Morocco", "Group C", {
      status: "in_play", period: "second_half", minute: 70, score_home: 1, score_away: 1,
      kickoff_utc: new Date(Date.now() - 60 * 60_000).toISOString(),
    }),
    match(2, "Qatar", "Switzerland", "Group B", {
      status: "finished", score_home: 1, score_away: 1, kickoff_utc: pastKickoff,
    }),
  ]);
  render(<MatchesPage />);
  await waitFor(() => expect(screen.getByText("Live now")).toBeInTheDocument());
  expect(screen.getByText("Morocco")).toBeInTheDocument(); // away team of the live match

  // The live match kicked off today, so it stays under Today (and pinned);
  // the older finished result drops away.
  fireEvent.click(screen.getByRole("tab", { name: "Today" }));
  expect(screen.getByText("Live now")).toBeInTheDocument();
  expect(screen.getByText("Morocco")).toBeInTheDocument();
  expect(screen.queryByText("Switzerland")).not.toBeInTheDocument();
});
