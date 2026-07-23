import { render, screen } from "@testing-library/react";
import { NrlTipsLeaderboard } from "./NrlTipsLeaderboard";
import { getNrlTipsLeaderboard } from "@/lib/nrlTips";

jest.mock("@/lib/nrlTips");

const mockLeaderboard = getNrlTipsLeaderboard as jest.MockedFunction<typeof getNrlTipsLeaderboard>;

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
