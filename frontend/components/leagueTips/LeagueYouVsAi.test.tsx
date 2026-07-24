import { render, screen } from "@testing-library/react";
import { LeagueYouVsAi } from "./LeagueYouVsAi";
import { getLeagueTipsSummary } from "@/lib/leagueTips";
import { getOrCreateDeviceId } from "@/lib/session";
import type { LeagueTipsSummaryResponse } from "@/lib/types";

jest.mock("@/lib/leagueTips");
jest.mock("@/lib/session", () => {
  const actual = jest.requireActual("@/lib/session");
  return { ...actual, getOrCreateDeviceId: jest.fn() };
});

const mockSummary = getLeagueTipsSummary as jest.MockedFunction<typeof getLeagueTipsSummary>;
const mockDeviceId = getOrCreateDeviceId as jest.MockedFunction<typeof getOrCreateDeviceId>;

// resetAllMocks (below) wipes any implementation set inside the jest.mock
// factory too, so the device id stub is (re)installed per test here.
beforeEach(() => mockDeviceId.mockReturnValue("device-1"));
afterEach(() => jest.resetAllMocks());

const DISCLAIMER = "For analytics and entertainment only. Not betting advice.";

it("invites predicting this matchweek when nothing is graded yet", async () => {
  const empty: LeagueTipsSummaryResponse = {
    league: "epl", handle: null, matchweeks: [],
    totals: { your_points: 0, model_points: 0, matchweeks_played: 0 },
    current_streak: 0, best_streak: 0, best_matchweek: null, disclaimer: DISCLAIMER,
  };
  mockSummary.mockResolvedValue(empty);

  render(<LeagueYouVsAi league="epl" />);
  expect(await screen.findByText(/Predict this matchweek to start your record/i)).toBeInTheDocument();
  expect(mockSummary).toHaveBeenCalledWith("epl", "device-1");
});

it("shows the per-matchweek and season totals once a matchweek has graded", async () => {
  const data: LeagueTipsSummaryResponse = {
    league: "epl", handle: "SwiftStriker42",
    matchweeks: [{ matchweek: 1, your_points: 5, model_points: 6, matches_played: 8 }],
    totals: { your_points: 5, model_points: 6, matchweeks_played: 1 },
    current_streak: 0, best_streak: 0, best_matchweek: null, disclaimer: DISCLAIMER,
  };
  mockSummary.mockResolvedValue(data);

  render(<LeagueYouVsAi league="epl" />);
  expect(await screen.findByText("5")).toBeInTheDocument();
  expect(screen.getByText("6")).toBeInTheDocument();
  expect(screen.getByText("1 matchweek graded")).toBeInTheDocument();
  expect(screen.getByText("Matchweek 1")).toBeInTheDocument();
});

it("hides the streak/best-matchweek chips when nothing is graded yet", async () => {
  const data: LeagueTipsSummaryResponse = {
    league: "epl", handle: "SwiftStriker42",
    matchweeks: [{ matchweek: 1, your_points: 5, model_points: 6, matches_played: 8 }],
    totals: { your_points: 5, model_points: 6, matchweeks_played: 1 },
    current_streak: 0, best_streak: 0, best_matchweek: null, disclaimer: DISCLAIMER,
  };
  mockSummary.mockResolvedValue(data);

  render(<LeagueYouVsAi league="epl" />);
  await screen.findByText("Matchweek 1");
  expect(screen.queryByText(/prediction streak/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Best matchweek/)).not.toBeInTheDocument();
});

it("shows the streak and best-matchweek chips once they're non-zero", async () => {
  const data: LeagueTipsSummaryResponse = {
    league: "epl", handle: "SwiftStriker42",
    matchweeks: [{ matchweek: 3, your_points: 6, model_points: 5, matches_played: 8 }],
    totals: { your_points: 6, model_points: 5, matchweeks_played: 1 },
    current_streak: 3, best_streak: 5, best_matchweek: { matchweek: 3, points: 6 }, disclaimer: DISCLAIMER,
  };
  mockSummary.mockResolvedValue(data);

  render(<LeagueYouVsAi league="epl" />);
  expect(await screen.findByText("3-prediction streak")).toBeInTheDocument();
  expect(screen.getByText("Best streak 5")).toBeInTheDocument();
  expect(screen.getByText("Best matchweek MW3 · 6")).toBeInTheDocument();
});

it("shares the player's own league share-page URL for a graded matchweek", async () => {
  const data: LeagueTipsSummaryResponse = {
    league: "epl", handle: "SwiftStriker42",
    matchweeks: [{ matchweek: 3, your_points: 6, model_points: 5, matches_played: 8 }],
    totals: { your_points: 6, model_points: 5, matchweeks_played: 1 },
    current_streak: 0, best_streak: 0, best_matchweek: null, disclaimer: DISCLAIMER,
  };
  mockSummary.mockResolvedValue(data);
  window.matchMedia = jest.fn().mockReturnValue({ matches: false }) as unknown as typeof window.matchMedia;
  const writeText = jest.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });

  render(<LeagueYouVsAi league="epl" />);
  const shareButton = await screen.findByRole("button");
  shareButton.click();

  await screen.findByText("Link copied!");
  expect(writeText).toHaveBeenCalledWith(
    "https://fifa-wc26-prediction.vercel.app/tips/share/epl/3/SwiftStriker42",
  );
});

it("omits the share affordance when the player has no handle yet", async () => {
  const data: LeagueTipsSummaryResponse = {
    league: "epl", handle: null,
    matchweeks: [{ matchweek: 3, your_points: 6, model_points: 5, matches_played: 8 }],
    totals: { your_points: 6, model_points: 5, matchweeks_played: 1 },
    current_streak: 0, best_streak: 0, best_matchweek: null, disclaimer: DISCLAIMER,
  };
  mockSummary.mockResolvedValue(data);

  render(<LeagueYouVsAi league="epl" />);
  await screen.findByText("Matchweek 3");
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("surfaces a load failure with a retry option", async () => {
  mockSummary.mockRejectedValue(new Error("boom"));
  render(<LeagueYouVsAi league="epl" />);
  expect(await screen.findByText(/Couldn't load your record/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
});
