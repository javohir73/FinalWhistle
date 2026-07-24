import { fireEvent, render, screen } from "@testing-library/react";
import { LeagueTipsLeaderboard } from "./LeagueTipsLeaderboard";
import { getLeagueSeasonLeaderboard, getLeagueTipsLeaderboard } from "@/lib/leagueTips";

jest.mock("@/lib/leagueTips");

const mockLeaderboard = getLeagueTipsLeaderboard as jest.MockedFunction<typeof getLeagueTipsLeaderboard>;
const mockSeasonLeaderboard = getLeagueSeasonLeaderboard as jest.MockedFunction<typeof getLeagueSeasonLeaderboard>;

afterEach(() => jest.resetAllMocks());

it("shows only a quiet participant count below the gate -- no empty table", async () => {
  mockLeaderboard.mockResolvedValue({ league: "epl", matchweek: 1, participant_count: 9, entries: [] });

  render(<LeagueTipsLeaderboard league="epl" matchweek={1} />);
  expect(await screen.findByText("9 playing this matchweek")).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

it("renders the ranked list with the exact-count tiebreak column once the matchweek hits the gate", async () => {
  mockLeaderboard.mockResolvedValue({
    league: "epl", matchweek: 1, participant_count: 10,
    entries: [{ handle: "SwiftStriker42", points: 7, exact_count: 2 }],
  });

  render(<LeagueTipsLeaderboard league="epl" matchweek={1} />);
  expect(await screen.findByRole("table")).toBeInTheDocument();
  expect(screen.getByText("SwiftStriker42")).toBeInTheDocument();
  expect(screen.getByText("7")).toBeInTheDocument();
  expect(screen.getByText("Exact")).toBeInTheDocument();
  expect(screen.getByText("2")).toBeInTheDocument();
});

it("never fetches the season endpoint before the Season tab is opened", async () => {
  mockLeaderboard.mockResolvedValue({ league: "epl", matchweek: 1, participant_count: 9, entries: [] });

  render(<LeagueTipsLeaderboard league="epl" matchweek={1} />);
  await screen.findByText("9 playing this matchweek");
  expect(mockSeasonLeaderboard).not.toHaveBeenCalled();
});

it("shows a quiet season participant count below the season gate -- no empty table", async () => {
  mockLeaderboard.mockResolvedValue({ league: "epl", matchweek: 1, participant_count: 9, entries: [] });
  mockSeasonLeaderboard.mockResolvedValue({ league: "epl", participant_count: 6, entries: [] });

  render(<LeagueTipsLeaderboard league="epl" matchweek={1} />);
  await screen.findByText("9 playing this matchweek");

  fireEvent.click(screen.getByRole("button", { name: "Season" }));
  expect(mockSeasonLeaderboard).toHaveBeenCalledWith("epl");
  expect(await screen.findByText("6 playing this season")).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

it("renders the season-long ranked list, matchweeks_played included, once the season hits the gate", async () => {
  mockLeaderboard.mockResolvedValue({ league: "epl", matchweek: 1, participant_count: 9, entries: [] });
  mockSeasonLeaderboard.mockResolvedValue({
    league: "epl", participant_count: 12,
    entries: [{ handle: "SwiftStriker123", points: 14, exact_count: 3, matchweeks_played: 6 }],
  });

  render(<LeagueTipsLeaderboard league="epl" matchweek={1} />);
  await screen.findByText("9 playing this matchweek");

  fireEvent.click(screen.getByRole("button", { name: "Season" }));
  expect(await screen.findByRole("table")).toBeInTheDocument();
  expect(screen.getByText("SwiftStriker123")).toBeInTheDocument();
  expect(screen.getByText("14")).toBeInTheDocument();
  expect(screen.getByText("3")).toBeInTheDocument();
  expect(screen.getByText("6")).toBeInTheDocument();
});

it("switches back to the weekly board without re-fetching it", async () => {
  mockLeaderboard.mockResolvedValue({
    league: "epl", matchweek: 1, participant_count: 10,
    entries: [{ handle: "SwiftStriker42", points: 7, exact_count: 1 }],
  });
  mockSeasonLeaderboard.mockResolvedValue({ league: "epl", participant_count: 6, entries: [] });

  render(<LeagueTipsLeaderboard league="epl" matchweek={1} />);
  await screen.findByRole("table");

  fireEvent.click(screen.getByRole("button", { name: "Season" }));
  await screen.findByText("6 playing this season");

  fireEvent.click(screen.getByRole("button", { name: "Weekly" }));
  expect(await screen.findByText("SwiftStriker42")).toBeInTheDocument();
  expect(mockLeaderboard).toHaveBeenCalledTimes(1);
});

it("re-fetches the weekly board when the matchweek prop changes", async () => {
  mockLeaderboard.mockResolvedValueOnce({ league: "epl", matchweek: 1, participant_count: 9, entries: [] });
  mockLeaderboard.mockResolvedValueOnce({ league: "epl", matchweek: 2, participant_count: 11, entries: [] });

  const { rerender } = render(<LeagueTipsLeaderboard league="epl" matchweek={1} />);
  await screen.findByText("9 playing this matchweek");

  rerender(<LeagueTipsLeaderboard league="epl" matchweek={2} />);
  expect(await screen.findByText("11 playing this matchweek")).toBeInTheDocument();
  expect(mockLeaderboard).toHaveBeenCalledWith("epl", 2);
});
