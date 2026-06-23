/** MatchLineups island: the four states — loading skeleton, available (pitch +
 *  bench + honest attribution), the { available:false } placeholder message, and
 *  an error with a working "Try again" (the shared useFetch / ErrorState path). */
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MatchLineups } from "@/components/MatchLineups";
import * as api from "@/lib/api";
import type { MatchLineups as MatchLineupsData } from "@/lib/types";

jest.mock("@/lib/api");
const mockGetMatchLineups = api.getMatchLineups as jest.Mock;

const available: MatchLineupsData = {
  available: true,
  message: null,
  fetched_at: "2026-06-23T18:00:00+00:00",
  home: {
    team: "Brazil",
    formation: "4-3-3",
    coach: "Tite",
    start_xi: [
      { name: "Alisson", number: 1, position: "G", grid: "1:1", is_starter: true },
      { name: "Marquinhos", number: 4, position: "D", grid: "2:2", is_starter: true },
      { name: "Casemiro", number: 5, position: "M", grid: "3:2", is_starter: true },
      { name: "Vinicius Junior", number: 10, position: "F", grid: "4:1", is_starter: true },
    ],
    bench: [{ name: "Ederson", number: 23, position: "G", grid: null, is_starter: false }],
  },
  away: {
    team: "Croatia",
    formation: "4-3-3",
    coach: "Dalic",
    start_xi: [
      { name: "Livakovic", number: 1, position: "G", grid: "1:1", is_starter: true },
    ],
    bench: [],
  },
};

afterEach(() => jest.resetAllMocks());

it("shows a loading skeleton while the fetch is in flight", () => {
  // A pending promise keeps useFetch in its loading state.
  mockGetMatchLineups.mockReturnValue(new Promise(() => {}));
  render(<MatchLineups matchId={1} />);
  expect(screen.getByRole("status", { name: /loading lineups/i })).toBeInTheDocument();
});

it("renders both teams' XI, bench and the API-Football attribution when available", async () => {
  mockGetMatchLineups.mockResolvedValue(available);
  render(<MatchLineups matchId={1} />);

  // Both teams share one pitch (home top half / away bottom half).
  expect(
    await screen.findByRole("group", { name: /Brazil versus Croatia/i }),
  ).toBeInTheDocument();
  // A starter shirt is keyboard-accessible with a descriptive label.
  expect(
    screen.getByRole("button", { name: /#10 Vinicius Junior \(F\)/ }),
  ).toBeInTheDocument();
  // The bench substitute is listed.
  expect(screen.getByText("Ederson")).toBeInTheDocument();
  // Honest source + fetched time.
  expect(
    screen.getByText(/Official lineup — via API-Football/),
  ).toBeInTheDocument();
  expect(screen.getByText(/fetched/)).toBeInTheDocument();
});

it("renders only the requested side when `side` is given", async () => {
  mockGetMatchLineups.mockResolvedValue(available);
  render(<MatchLineups matchId={1} side="home" />);

  expect(await screen.findByText("Brazil")).toBeInTheDocument();
  expect(screen.queryByText("Croatia")).not.toBeInTheDocument();
});

it("shows the placeholder message (no fabricated data) when unavailable", async () => {
  mockGetMatchLineups.mockResolvedValue({
    available: false,
    message: "Lineups are announced ~40 minutes before kickoff.",
    home: null,
    away: null,
    fetched_at: null,
  } satisfies MatchLineupsData);
  render(<MatchLineups matchId={1} />);

  expect(
    await screen.findByText(/announced ~40 minutes before kickoff/i),
  ).toBeInTheDocument();
  // No pitch / attribution rendered for the placeholder.
  expect(screen.queryByText(/via API-Football/)).not.toBeInTheDocument();
});

it("shows an error with a working Try again that recovers", async () => {
  mockGetMatchLineups.mockRejectedValueOnce(new Error("offline"));
  render(<MatchLineups matchId={1} />);

  // Error state surfaces with the retry affordance.
  const retry = await screen.findByRole("button", { name: /try again/i });
  expect(screen.getByRole("alert")).toBeInTheDocument();

  // Next attempt succeeds → retry clears the error and renders the lineup.
  mockGetMatchLineups.mockResolvedValue(available);
  fireEvent.click(retry);

  await waitFor(() =>
    expect(screen.getByRole("group", { name: /Brazil versus Croatia/i })).toBeInTheDocument(),
  );
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
