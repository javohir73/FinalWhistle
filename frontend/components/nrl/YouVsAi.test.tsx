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
    current_streak: 0, best_streak: 0, best_round: null,
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
    current_streak: 0, best_streak: 0, best_round: null,
    disclaimer: "For analytics and entertainment only. Not betting advice.",
  };
  mockSummary.mockResolvedValue(data);

  render(<YouVsAi />);
  expect(await screen.findByText("5")).toBeInTheDocument();
  expect(screen.getByText("6")).toBeInTheDocument();
  expect(screen.getByText("1 round graded")).toBeInTheDocument();
  expect(screen.getByText("Round 1")).toBeInTheDocument();
});

it("hides the streak/best-round chips when nothing is graded yet", async () => {
  const data: NrlTipsSummaryResponse = {
    handle: "SwiftHalfback482",
    rounds: [{ season: 2026, round: 1, your_points: 5, model_points: 6, matches_played: 8 }],
    totals: { your_points: 5, model_points: 6, rounds_played: 1 },
    current_streak: 0, best_streak: 0, best_round: null,
    disclaimer: "For analytics and entertainment only. Not betting advice.",
  };
  mockSummary.mockResolvedValue(data);

  render(<YouVsAi />);
  await screen.findByText("Round 1");
  expect(screen.queryByText(/pick streak/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Best round/)).not.toBeInTheDocument();
});

it("shows the streak and best-round chips once they're non-zero", async () => {
  const data: NrlTipsSummaryResponse = {
    handle: "SwiftHalfback482",
    rounds: [{ season: 2026, round: 3, your_points: 6, model_points: 5, matches_played: 8 }],
    totals: { your_points: 6, model_points: 5, rounds_played: 1 },
    current_streak: 3, best_streak: 5, best_round: { round: 3, points: 6 },
    disclaimer: "For analytics and entertainment only. Not betting advice.",
  };
  mockSummary.mockResolvedValue(data);

  render(<YouVsAi />);
  expect(await screen.findByText("3-pick streak")).toBeInTheDocument();
  expect(screen.getByText("Best streak 5")).toBeInTheDocument();
  expect(screen.getByText("Best round Rd 3 · 6")).toBeInTheDocument();
});

it("shares the player's own share-page URL for a graded round", async () => {
  const data: NrlTipsSummaryResponse = {
    handle: "SwiftHalfback482",
    rounds: [{ season: 2026, round: 3, your_points: 6, model_points: 5, matches_played: 8 }],
    totals: { your_points: 6, model_points: 5, rounds_played: 1 },
    current_streak: 0, best_streak: 0, best_round: null,
    disclaimer: "For analytics and entertainment only. Not betting advice.",
  };
  mockSummary.mockResolvedValue(data);
  window.matchMedia = jest.fn().mockReturnValue({ matches: false }) as unknown as typeof window.matchMedia;
  const writeText = jest.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });

  render(<YouVsAi />);
  // ShareButton's accessible name is its constant aria-label ("Share this
  // page"), not the visible `label` text -- same as ShareButton.test.tsx.
  const shareButton = await screen.findByRole("button");
  shareButton.click();

  await screen.findByText("Link copied!");
  expect(writeText).toHaveBeenCalledWith(
    "https://fifa-wc26-prediction.vercel.app/nrl/tips/share/2026/3/SwiftHalfback482",
  );
});

it("omits the share affordance when the player has no handle yet", async () => {
  const data: NrlTipsSummaryResponse = {
    handle: null,
    rounds: [{ season: 2026, round: 3, your_points: 6, model_points: 5, matches_played: 8 }],
    totals: { your_points: 6, model_points: 5, rounds_played: 1 },
    current_streak: 0, best_streak: 0, best_round: null,
    disclaimer: "For analytics and entertainment only. Not betting advice.",
  };
  mockSummary.mockResolvedValue(data);

  render(<YouVsAi />);
  await screen.findByText("Round 3");
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("surfaces a load failure with a retry option", async () => {
  mockSummary.mockRejectedValue(new Error("boom"));
  render(<YouVsAi />);
  expect(await screen.findByText(/Couldn't load your record/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
});
