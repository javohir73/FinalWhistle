/** Regression for the league switcher leaking LeagueTipsPicker's internal nav
 *  state across a league change (Opus review, League Score Predictions
 *  Phase 2 multi-league switcher). Unlike LeagueTipsPlaySection.
 *  multiLeague.test.tsx (which mocks LeagueTipsPicker out entirely and so
 *  never exercises its internal `requested`/`current`/`boundary` state),
 *  this file renders the REAL picker and asserts a league switch drops the
 *  prior league's matchweek/fixtures instead of re-requesting the old
 *  league's matchweek number or falling back to showing its stale payload. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LeagueTipsPlaySection } from "./LeagueTipsPlaySection";
import { getMyLeagueTips } from "@/lib/leagueTips";
import { ApiError, getOrCreateDeviceId } from "@/lib/session";
import type { LeagueTipsMineResponse } from "@/lib/types";

jest.mock("@/lib/leagueConfig", () => ({
  DEFAULT_LEAGUE: "epl",
  ACTIVE_LEAGUES: ["epl", "laliga"],
  leagueLabel: (league: string) => ({ epl: "Premier League", laliga: "La Liga" })[league] ?? league.toUpperCase(),
}));
jest.mock("@/components/leagueTips/ClaimDeviceLeagueTips", () => ({
  ClaimDeviceLeagueTips: () => <div data-testid="claim" />,
}));
jest.mock("@/components/leagueTips/LeagueYouVsAi", () => ({
  LeagueYouVsAi: ({ league }: { league: string }) => <div data-testid="you-vs-ai">{league}</div>,
}));
jest.mock("@/components/leagueTips/LeagueTipsLeaderboard", () => ({
  LeagueTipsLeaderboard: ({ league, matchweek }: { league: string; matchweek: number }) => (
    <div data-testid="leaderboard">{`${league}-${matchweek}`}</div>
  ),
}));
jest.mock("@/lib/leagueTips");
jest.mock("@/lib/session", () => {
  const actual = jest.requireActual("@/lib/session");
  return { ...actual, getOrCreateDeviceId: jest.fn() };
});

const mockMine = getMyLeagueTips as jest.MockedFunction<typeof getMyLeagueTips>;
const mockDeviceId = getOrCreateDeviceId as jest.MockedFunction<typeof getOrCreateDeviceId>;

beforeEach(() => {
  localStorage.clear();
  mockDeviceId.mockReturnValue("device-1");
});
afterEach(() => jest.resetAllMocks());

function mine(overrides: Partial<LeagueTipsMineResponse>): LeagueTipsMineResponse {
  return {
    league: "epl",
    matchweek: 3,
    handle: null,
    matches: [],
    disclaimer: "For analytics and entertainment only. Not betting advice.",
    ...overrides,
  };
}

it("drops the prior league's matchweek/fixtures on switch instead of re-requesting its matchweek number", async () => {
  // epl: matchweek 3 loads fine; matchweek 4 (the "next" nav target) is off
  // the end -- exercises the "keep showing the last good matchweek" branch,
  // which is exactly what must NOT survive a league switch.
  // laliga: only its CURRENT matchweek (requested=undefined) resolves --
  // any explicit `requested` number 404s, so a stale carried-over
  // `requested` from epl would surface as the bug this test guards against.
  mockMine.mockImplementation((league, _deviceId, requested) => {
    if (league === "epl") {
      if (requested === 4) {
        return Promise.reject(new ApiError(404, "matchweek_not_found", "No matches for matchweek 4"));
      }
      return Promise.resolve(
        mine({
          league: "epl", matchweek: 3,
          matches: [{
            id: 501, home: "Arsenal", away: "Chelsea", kickoff_utc: null, status: "scheduled",
            score_home: null, score_away: null, model: null, your_prediction: null,
          }],
        }),
      );
    }
    if (league === "laliga") {
      if (requested != null) {
        return Promise.reject(new ApiError(404, "matchweek_not_found", "No matches for that matchweek"));
      }
      return Promise.resolve(
        mine({
          league: "laliga", matchweek: 5,
          matches: [{
            id: 701, home: "Real Madrid", away: "Barcelona", kickoff_utc: null, status: "scheduled",
            score_home: null, score_away: null, model: null, your_prediction: null,
          }],
        }),
      );
    }
    return Promise.reject(new Error(`unexpected league ${league}`));
  });

  render(<LeagueTipsPlaySection defaultLeague="epl" />);

  await screen.findByText("Matchweek 3");
  expect(await screen.findByRole("group", { name: /Arsenal vs Chelsea/i })).toBeInTheDocument();

  // Run epl's nav off the end -- sets internal `requested`/`boundary` state
  // on the picker that must NOT survive a subsequent league switch.
  fireEvent.click(screen.getByRole("button", { name: /Matchweek 4/ }));
  await screen.findByText(/No epl matches loaded for that matchweek yet\./);

  fireEvent.click(screen.getByRole("button", { name: "La Liga" }));

  // The remount must request La Liga's CURRENT matchweek (requested
  // undefined), never epl's stale requested=4.
  await waitFor(() => expect(mockMine).toHaveBeenCalledWith("laliga", "device-1", undefined));
  expect(await screen.findByText("Matchweek 5")).toBeInTheDocument();
  expect(await screen.findByRole("group", { name: /Real Madrid vs Barcelona/i })).toBeInTheDocument();

  // Never shows epl's stale fixture/matchweek mislabeled as La Liga's.
  expect(screen.queryByText("Arsenal")).not.toBeInTheDocument();
  expect(screen.queryByText("Matchweek 3")).not.toBeInTheDocument();
  expect(screen.queryByText(/No .* matches loaded for that matchweek yet\./)).not.toBeInTheDocument();
});
