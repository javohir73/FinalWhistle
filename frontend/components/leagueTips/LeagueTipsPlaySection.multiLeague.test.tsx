/** Three-active-league behavior for the /tips switcher (design doc: League
 *  Score Predictions Phase 2 -- 2026-07-24). lib/leagueConfig.ts is mocked
 *  here (jest.mock is hoisted/file-scoped, so this can't share a file with
 *  LeagueTipsPlaySection.test.tsx's real-config, switcher-hidden case) to a
 *  3-league roster the way the backend tests inject a second Tournament via
 *  monkeypatch.setitem on _LEAGUE_TOURNAMENT_NAMES -- same "override the
 *  registry for the test only" idiom, just on the frontend's config module. */
import { fireEvent, render, screen } from "@testing-library/react";
import { LeagueTipsPlaySection } from "./LeagueTipsPlaySection";

jest.mock("@/lib/leagueConfig", () => ({
  DEFAULT_LEAGUE: "epl",
  ACTIVE_LEAGUES: ["epl", "laliga", "bundesliga"],
  leagueLabel: (league: string) =>
    ({ epl: "Premier League", laliga: "La Liga", bundesliga: "Bundesliga" })[league] ?? league.toUpperCase(),
}));
jest.mock("@/components/leagueTips/ClaimDeviceLeagueTips", () => ({
  ClaimDeviceLeagueTips: () => <div data-testid="claim" />,
}));
jest.mock("@/components/leagueTips/LeagueTipsPicker", () => ({
  LeagueTipsPicker: ({
    league,
    onMatchweekChange,
  }: {
    league: string;
    onMatchweekChange?: (mw: number) => void;
  }) => (
    <div data-testid="picker">
      {league}
      <button onClick={() => onMatchweekChange?.(league === "epl" ? 3 : 7)}>resolve matchweek</button>
    </div>
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

it("shows the switcher, labeled per league, once more than one league is active", () => {
  render(<LeagueTipsPlaySection defaultLeague="epl" />);
  expect(screen.getByLabelText("League")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Premier League" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "La Liga" })).toHaveAttribute("aria-pressed", "false");
  expect(screen.getByRole("button", { name: "Bundesliga" })).toHaveAttribute("aria-pressed", "false");
});

it("swaps the league prop through the picker, you-vs-ai section and leaderboard on switch, clearing the stale matchweek", () => {
  render(<LeagueTipsPlaySection defaultLeague="epl" />);

  fireEvent.click(screen.getByRole("button", { name: "resolve matchweek" }));
  expect(screen.getByTestId("leaderboard")).toHaveTextContent("epl-3");

  fireEvent.click(screen.getByRole("button", { name: "La Liga" }));
  expect(screen.getByTestId("picker")).toHaveTextContent("laliga");
  expect(screen.getByTestId("you-vs-ai")).toHaveTextContent("laliga");
  // Old matchweek must not survive the switch -- the leaderboard would
  // otherwise show La Liga standings for an EPL matchweek number.
  expect(screen.queryByTestId("leaderboard")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "La Liga" })).toHaveAttribute("aria-pressed", "true");

  fireEvent.click(screen.getByRole("button", { name: "resolve matchweek" }));
  expect(screen.getByTestId("leaderboard")).toHaveTextContent("laliga-7");
});
