/** Real three-league configuration. */
import { fireEvent, render, screen } from "@testing-library/react";
import { LeagueTipsPlaySection } from "./LeagueTipsPlaySection";

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
      <button onClick={() => onMatchweekChange?.(4)}>resolve matchweek</button>
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

it("shows every active league in the switcher", () => {
  render(<LeagueTipsPlaySection defaultLeague="epl" />);
  expect(screen.getByLabelText("League")).toBeInTheDocument();
  for (const league of ["Premier League", "La Liga", "Bundesliga"]) {
    expect(screen.getByRole("button", { name: league })).toBeInTheDocument();
  }
  expect(screen.queryByRole("button", { name: "UEFA Champions League" })).not.toBeInTheDocument();
});

it("can suppress the switcher when a parent renders one fixed league", () => {
  render(<LeagueTipsPlaySection defaultLeague="laliga" showLeagueSwitcher={false} />);
  expect(screen.queryByLabelText("League")).not.toBeInTheDocument();
  expect(screen.getByTestId("picker")).toHaveTextContent("laliga");
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

it("mounts the in-section leaderboard once the matchweek resolves (showLeaderboard defaults true)", () => {
  render(<LeagueTipsPlaySection defaultLeague="epl" />);
  fireEvent.click(screen.getByRole("button", { name: "resolve matchweek" }));
  expect(screen.getByTestId("leaderboard")).toHaveTextContent("epl-4");
});

it("keeps the in-section leaderboard out when showLeaderboard is false (hub hoists it)", () => {
  render(<LeagueTipsPlaySection defaultLeague="epl" showLeaderboard={false} />);
  // Even after the matchweek resolves, the section renders no board of its own.
  fireEvent.click(screen.getByRole("button", { name: "resolve matchweek" }));
  expect(screen.queryByTestId("leaderboard")).not.toBeInTheDocument();
});

it("reports the resolved matchweek through onMatchweekResolved, even with the board suppressed", () => {
  const onMatchweekResolved = jest.fn();
  render(
    <LeagueTipsPlaySection
      defaultLeague="epl"
      showLeaderboard={false}
      onMatchweekResolved={onMatchweekResolved}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "resolve matchweek" }));
  expect(onMatchweekResolved).toHaveBeenCalledWith(4);
});
