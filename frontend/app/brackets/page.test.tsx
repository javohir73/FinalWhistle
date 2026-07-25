/** The bracket route is explicitly the WC26 surface. It must not disappear
 *  merely because a domestic league is the globally active tournament. */
import { render, screen } from "@testing-library/react";
import BracketsPage from "./page";
import * as api from "@/lib/api";
import type { ActiveTournament } from "@/lib/types";

jest.mock("@/lib/api", () => ({
  ...jest.requireActual("@/lib/api"),
  getCompetitionTournamentServer: jest.fn(),
}));
const mockTournament = api.getCompetitionTournamentServer as jest.MockedFunction<
  typeof api.getCompetitionTournamentServer
>;

afterEach(() => jest.resetAllMocks());

it("renders the WC26 bracket UI when the endpoint 404s (fallback)", async () => {
  mockTournament.mockResolvedValue(null);
  render(await BracketsPage());
  expect(screen.getByRole("heading", { name: "Official bracket" })).toBeInTheDocument();
});

it("does not substitute the active domestic league for the WC26 bracket", async () => {
  const league: ActiveTournament = {
    id: 1,
    name: "Premier League 2026-27",
    year: 2026,
    format: "league",
    has_brackets: false,
  };
  mockTournament.mockImplementation(async (competition) =>
    competition === "wc26" ? null : league,
  );
  render(await BracketsPage());

  expect(screen.getByRole("heading", { name: "Official bracket" })).toBeInTheDocument();
  expect(mockTournament).toHaveBeenCalledWith("wc26");
});
