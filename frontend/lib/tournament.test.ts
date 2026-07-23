/** getTournament() must degrade to the WC26 fallback on anything short of a
 *  clean 200 from /api/tournaments/active — this PR ships before the backend
 *  workstream does (docs/LEAGUE-PIVOT-PLAN.md D5/D6). */
import { getTournament, WC26_FALLBACK } from "./tournament";
import { getActiveTournamentServer } from "./api";
import type { ActiveTournament } from "./types";

jest.mock("./api");
const mockGet = getActiveTournamentServer as jest.MockedFunction<typeof getActiveTournamentServer>;

afterEach(() => jest.resetAllMocks());

it("returns the fetched tournament on success", async () => {
  const league: ActiveTournament = {
    id: 1,
    name: "Premier League 2026-27",
    year: 2026,
    format: "league",
    has_brackets: false,
  };
  mockGet.mockResolvedValue(league);
  expect(await getTournament()).toEqual(league);
});

it("falls back to WC26 on a 404 (null)", async () => {
  mockGet.mockResolvedValue(null);
  expect(await getTournament()).toEqual(WC26_FALLBACK);
});

it("falls back to WC26 on a network/parse error", async () => {
  mockGet.mockRejectedValue(new Error("network down"));
  expect(await getTournament()).toEqual(WC26_FALLBACK);
});
