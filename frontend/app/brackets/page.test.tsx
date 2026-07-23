/** Brackets page — server component (SSR) output. C6/D6 (league pivot): a
 *  tournament with no knockout stage gets a friendly empty state instead of
 *  the WC26 bracket UI. See docs/LEAGUE-PIVOT-PLAN.md.
 *
 *  Only getActiveTournamentServer is mocked — every other api.ts export stays
 *  real (as in bracketsClient.test.tsx), so the client island's real fetches
 *  reject harmlessly in jsdom instead of crashing on an auto-mocked non-Promise. */
import { render, screen } from "@testing-library/react";
import BracketsPage from "./page";
import * as api from "@/lib/api";
import type { ActiveTournament } from "@/lib/types";

jest.mock("@/lib/api", () => ({
  ...jest.requireActual("@/lib/api"),
  getActiveTournamentServer: jest.fn(),
}));
const mockTournament = api.getActiveTournamentServer as jest.MockedFunction<
  typeof api.getActiveTournamentServer
>;

afterEach(() => jest.resetAllMocks());

it("renders the WC26 bracket UI when the endpoint 404s (fallback)", async () => {
  mockTournament.mockResolvedValue(null);
  render(await BracketsPage());
  expect(screen.getByRole("heading", { name: "Official bracket" })).toBeInTheDocument();
});

it("shows a friendly no-bracket state with a link to fixtures for a league", async () => {
  const league: ActiveTournament = {
    id: 1,
    name: "Premier League 2026-27",
    year: 2026,
    format: "league",
    has_brackets: false,
  };
  mockTournament.mockResolvedValue(league);
  render(await BracketsPage());

  expect(screen.queryByRole("heading", { name: "Official bracket" })).not.toBeInTheDocument();
  expect(screen.getByText(/doesn't have a knockout bracket/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "See fixtures" })).toHaveAttribute("href", "/matches");
});
