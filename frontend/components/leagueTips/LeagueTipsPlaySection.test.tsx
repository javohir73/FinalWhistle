/** Real lib/leagueConfig.ts (today's actual EPL-only ACTIVE_LEAGUES) --
 *  proves the switcher stays hidden and /tips renders exactly what it does
 *  today with no config override. The three-active-league behavior (switcher
 *  shown, league swapped through every child) lives in
 *  LeagueTipsPlaySection.multiLeague.test.tsx, which mocks lib/leagueConfig
 *  instead -- jest.mock is file-scoped/hoisted, so a single active-leagues
 *  count can't vary test-to-test within one file. */
import { render, screen } from "@testing-library/react";
import { LeagueTipsPlaySection } from "./LeagueTipsPlaySection";

jest.mock("@/components/leagueTips/ClaimDeviceLeagueTips", () => ({
  ClaimDeviceLeagueTips: () => <div data-testid="claim" />,
}));
jest.mock("@/components/leagueTips/LeagueTipsPicker", () => ({
  LeagueTipsPicker: ({ league }: { league: string; onMatchweekChange?: (mw: number) => void }) => (
    <div data-testid="picker">{league}</div>
  ),
}));
jest.mock("@/components/leagueTips/LeagueYouVsAi", () => ({
  LeagueYouVsAi: ({ league }: { league: string }) => <div data-testid="you-vs-ai">{league}</div>,
}));
jest.mock("@/components/leagueTips/LeagueTipsLeaderboard", () => ({
  LeagueTipsLeaderboard: ({ league, matchweek }: { league: string; matchweek: number }) => (
    <div data-testid="leaderboard">{`${league}-${matchweek}`}</div>
  ),
}));

it("hides the league switcher when the real config has only one active league", () => {
  render(<LeagueTipsPlaySection defaultLeague="epl" />);
  expect(screen.queryByLabelText("League")).not.toBeInTheDocument();
});

it("passes the default league down to the picker and you-vs-ai section", () => {
  render(<LeagueTipsPlaySection defaultLeague="epl" />);
  expect(screen.getByTestId("picker")).toHaveTextContent("epl");
  expect(screen.getByTestId("you-vs-ai")).toHaveTextContent("epl");
});

it("does not mount the leaderboard until a matchweek is known", () => {
  render(<LeagueTipsPlaySection defaultLeague="epl" />);
  expect(screen.queryByTestId("leaderboard")).not.toBeInTheDocument();
});
