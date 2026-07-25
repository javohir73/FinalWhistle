/** Play hub page -- server component (SSR) output. This slice (p5-s2) fills the
 *  Football group, so the test checks the server wiring on top of the shell:
 *  it renders both sport group headings, seeds the NRL group from
 *  getNrlTipsheetServer (degrading when that returns null/rejects), and -- new
 *  here -- surfaces the /brackets entry with the predicted champion (top
 *  win_title team) and mounts the reused league tips picker. The bracket entry
 *  gates on the active tournament's has_brackets, exactly as app/brackets does,
 *  so a league-format tournament renders the league tips only (honest degrade).
 *  The NRL pick sections arrive in p5-s3. The league tips leaf components are
 *  stubbed the same way components/leagueTips/*.test.tsx do -- this test is
 *  about the composition, not the picker's own fetch machinery. */
import { render, screen } from "@testing-library/react";
import PlayPage from "./page";
import {
  getActiveTournamentServer,
  getKnockoutOddsServer,
  getNrlTipsheetServer,
} from "@/lib/api";
import type { ActiveTournament, NrlTipsheet, TournamentOdds } from "@/lib/types";

jest.mock("@/lib/api");
const mockTipsheet = getNrlTipsheetServer as jest.MockedFunction<typeof getNrlTipsheetServer>;
const mockKnockoutOdds = getKnockoutOddsServer as jest.MockedFunction<typeof getKnockoutOddsServer>;
const mockActiveTournament = getActiveTournamentServer as jest.MockedFunction<
  typeof getActiveTournamentServer
>;

// The Football group renders the real LeagueTipsPlaySection, whose leaf
// components each fetch on mount -- stub them (mirrors
// components/leagueTips/LeagueTipsPlaySection.test.tsx) so this test exercises
// the composition, not their client fetch/localStorage paths.
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

const tipsheet: NrlTipsheet = {
  season: 2026,
  round: 2,
  matches: [],
  record: {
    evaluated_matches: 0, winner_accuracy: null, winner_accuracy_ci95: null,
    avg_log_loss: null, avg_brier: null, best_streak: 0, last_updated: null,
  },
  worst_miss: null,
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

const odd = (team_id: number, team: string, win_title: number | null): TournamentOdds => ({
  team_id, team, make_knockout: null, reach_r16: null, reach_qf: null, reach_sf: null,
  reach_final: null, win_title,
});
// Brazil leads on win_title -> the predicted champion the card should print.
const odds: TournamentOdds[] = [odd(1, "France", 0.15), odd(2, "Brazil", 0.18)];

const leagueTournament: ActiveTournament = {
  id: 9, name: "Premier League", year: 2026, format: "league", has_brackets: false,
};

// getActiveTournamentServer is left unset by default: the auto-mock returns
// undefined, so lib/tournament's getTournament falls back to WC26 (has_brackets
// true) -- today's live behavior. Tests that need a league-format tournament set
// it explicitly.
beforeEach(() => {
  mockTipsheet.mockResolvedValue(tipsheet);
  mockKnockoutOdds.mockResolvedValue(odds);
});
afterEach(() => jest.resetAllMocks());

it("renders the Play title and both sport group headings", async () => {
  render(await PlayPage());

  expect(screen.getByRole("heading", { level: 1, name: "Play" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Football" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "NRL" })).toBeInTheDocument();
});

it("seeds the NRL group with the current round when the tipsheet loads", async () => {
  render(await PlayPage());

  expect(mockTipsheet).toHaveBeenCalledWith();
  expect(screen.getByText("Round 2 · 2026")).toBeInTheDocument();
});

it("degrades (both groups render, no round line, no crash) when the tipsheet is null", async () => {
  mockTipsheet.mockResolvedValue(null);
  render(await PlayPage());

  expect(screen.getByRole("heading", { name: "Football" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "NRL" })).toBeInTheDocument();
  expect(screen.queryByText(/^Round /)).not.toBeInTheDocument();
});

it("degrades (no crash) when the NRL tipsheet fetch rejects", async () => {
  mockTipsheet.mockRejectedValue(new Error("upstream down"));
  render(await PlayPage());

  expect(screen.getByRole("heading", { name: "Football" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "NRL" })).toBeInTheDocument();
});

it("shows the World Cup bracket card linking to /brackets with the predicted champion", async () => {
  render(await PlayPage());

  const bracketLink = screen.getByRole("link", { name: /Projected knockout bracket/i });
  expect(bracketLink).toHaveAttribute("href", "/brackets");
  expect(bracketLink).toHaveTextContent("Brazil");
  expect(bracketLink).toHaveTextContent("18%");
});

it("degrades the bracket card to a plain link when the knockout odds are unavailable", async () => {
  mockKnockoutOdds.mockResolvedValue(null);
  render(await PlayPage());

  const bracketLink = screen.getByRole("link", { name: /Projected knockout bracket/i });
  expect(bracketLink).toHaveAttribute("href", "/brackets");
  expect(bracketLink).not.toHaveTextContent("Predicted champion");
});

it("mounts the reused league tips picker in the Football group", async () => {
  render(await PlayPage());

  expect(screen.getByTestId("picker")).toHaveTextContent("epl");
});

it("hides the bracket card for a league-format tournament, keeping the league tips", async () => {
  mockActiveTournament.mockResolvedValue(leagueTournament);
  render(await PlayPage());

  expect(screen.queryByRole("link", { name: /Projected knockout bracket/i })).not.toBeInTheDocument();
  expect(screen.getByTestId("picker")).toHaveTextContent("epl");
});
