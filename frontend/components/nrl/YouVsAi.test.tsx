import { render, screen } from "@testing-library/react";
import { YouVsAi } from "./YouVsAi";
import { getNrlTipsSummary } from "@/lib/nrlTips";
import { getOrCreateDeviceId } from "@/lib/session";
import type { NrlTipsSummaryResponse } from "@/lib/types";

jest.mock("@/lib/nrlTips");
jest.mock("@/lib/session", () => {
  const actual = jest.requireActual("@/lib/session");
  return { ...actual, getOrCreateDeviceId: jest.fn() };
});

const mockSummary = getNrlTipsSummary as jest.MockedFunction<typeof getNrlTipsSummary>;
const mockDeviceId = getOrCreateDeviceId as jest.MockedFunction<typeof getOrCreateDeviceId>;

// resetAllMocks (below) wipes any implementation set inside the jest.mock
// factory too, so the device id stub is (re)installed per test here.
beforeEach(() => mockDeviceId.mockReturnValue("device-1"));
afterEach(() => jest.resetAllMocks());

it("invites playing this round when nothing is graded yet", async () => {
  const empty: NrlTipsSummaryResponse = {
    handle: null, rounds: [], totals: { your_points: 0, model_points: 0, rounds_played: 0 },
    disclaimer: "For analytics and entertainment only. Not betting advice.",
  };
  mockSummary.mockResolvedValue(empty);

  render(<YouVsAi />);
  expect(await screen.findByText(/Play this round to start your record/i)).toBeInTheDocument();
});

it("shows the per-round and season totals once a round has graded", async () => {
  const data: NrlTipsSummaryResponse = {
    handle: "SwiftHalfback482",
    rounds: [{ season: 2026, round: 1, your_points: 5, model_points: 6, matches_played: 8 }],
    totals: { your_points: 5, model_points: 6, rounds_played: 1 },
    disclaimer: "For analytics and entertainment only. Not betting advice.",
  };
  mockSummary.mockResolvedValue(data);

  render(<YouVsAi />);
  expect(await screen.findByText("5")).toBeInTheDocument();
  expect(screen.getByText("6")).toBeInTheDocument();
  expect(screen.getByText("1 round graded")).toBeInTheDocument();
  expect(screen.getByText("Round 1")).toBeInTheDocument();
});

it("surfaces a load failure with a retry option", async () => {
  mockSummary.mockRejectedValue(new Error("boom"));
  render(<YouVsAi />);
  expect(await screen.findByText(/Couldn't load your record/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
});
