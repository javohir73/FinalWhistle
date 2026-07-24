import { fireEvent, render, screen } from "@testing-library/react";
import { NrlTipsLeaderboard } from "./NrlTipsLeaderboard";
import { getNrlSeasonLeaderboard, getNrlTipsLeaderboard } from "@/lib/nrlTips";

jest.mock("@/lib/nrlTips");

const mockLeaderboard = getNrlTipsLeaderboard as jest.MockedFunction<typeof getNrlTipsLeaderboard>;
const mockSeasonLeaderboard = getNrlSeasonLeaderboard as jest.MockedFunction<typeof getNrlSeasonLeaderboard>;

afterEach(() => jest.resetAllMocks());

it("shows only a quiet participant count below the gate -- no empty table", async () => {
  mockLeaderboard.mockResolvedValue({ season: 2026, round: 1, participant_count: 9, entries: [] });

  render(<NrlTipsLeaderboard season={2026} round={1} />);
  expect(await screen.findByText("9 playing this round")).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

it("renders the ranked list once the round hits the gate", async () => {
  mockLeaderboard.mockResolvedValue({
    season: 2026, round: 1, participant_count: 10,
    entries: [{ handle: "SwiftHalfback482", points: 7, round_margin: 3 }],
  });

  render(<NrlTipsLeaderboard season={2026} round={1} />);
  expect(await screen.findByRole("table")).toBeInTheDocument();
  expect(screen.getByText("SwiftHalfback482")).toBeInTheDocument();
  expect(screen.getByText("7")).toBeInTheDocument();
  expect(screen.getByText("3")).toBeInTheDocument();
});

it("shows an em dash for an entry with no featured-match margin", async () => {
  mockLeaderboard.mockResolvedValue({
    season: 2026, round: 1, participant_count: 10,
    entries: [{ handle: "BraveProp7", points: 4, round_margin: null }],
  });

  render(<NrlTipsLeaderboard season={2026} round={1} />);
  expect(await screen.findByText("—")).toBeInTheDocument();
});

it("never fetches the season endpoint before the Season tab is opened", async () => {
  mockLeaderboard.mockResolvedValue({ season: 2026, round: 1, participant_count: 9, entries: [] });

  render(<NrlTipsLeaderboard season={2026} round={1} />);
  await screen.findByText("9 playing this round");
  expect(mockSeasonLeaderboard).not.toHaveBeenCalled();
});

it("shows a quiet season participant count below the season gate -- no empty table", async () => {
  mockLeaderboard.mockResolvedValue({ season: 2026, round: 1, participant_count: 9, entries: [] });
  mockSeasonLeaderboard.mockResolvedValue({ season: 2026, participant_count: 6, entries: [] });

  render(<NrlTipsLeaderboard season={2026} round={1} />);
  await screen.findByText("9 playing this round");

  fireEvent.click(screen.getByRole("button", { name: "Season" }));
  expect(mockSeasonLeaderboard).toHaveBeenCalledWith(2026);
  expect(await screen.findByText("6 playing this season")).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

it("renders the season-long ranked list, rounds_played included, once the season hits the gate", async () => {
  mockLeaderboard.mockResolvedValue({ season: 2026, round: 1, participant_count: 9, entries: [] });
  mockSeasonLeaderboard.mockResolvedValue({
    season: 2026, participant_count: 12,
    entries: [{ handle: "SwiftHalfback123", points: 14, total_margin: 37, rounds_played: 6 }],
  });

  render(<NrlTipsLeaderboard season={2026} round={1} />);
  await screen.findByText("9 playing this round");

  fireEvent.click(screen.getByRole("button", { name: "Season" }));
  expect(await screen.findByRole("table")).toBeInTheDocument();
  expect(screen.getByText("SwiftHalfback123")).toBeInTheDocument();
  expect(screen.getByText("14")).toBeInTheDocument();
  expect(screen.getByText("37")).toBeInTheDocument();
  expect(screen.getByText("6")).toBeInTheDocument();
});

it("switches back to the weekly board without re-fetching it", async () => {
  mockLeaderboard.mockResolvedValue({
    season: 2026, round: 1, participant_count: 10,
    entries: [{ handle: "SwiftHalfback482", points: 7, round_margin: 3 }],
  });
  mockSeasonLeaderboard.mockResolvedValue({ season: 2026, participant_count: 6, entries: [] });

  render(<NrlTipsLeaderboard season={2026} round={1} />);
  await screen.findByRole("table");

  fireEvent.click(screen.getByRole("button", { name: "Season" }));
  await screen.findByText("6 playing this season");

  fireEvent.click(screen.getByRole("button", { name: "Weekly" }));
  expect(await screen.findByText("SwiftHalfback482")).toBeInTheDocument();
  expect(mockLeaderboard).toHaveBeenCalledTimes(1);
});
