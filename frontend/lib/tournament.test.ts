/** getTournament() must degrade to the WC26 fallback on anything short of a
 *  clean 200 from /api/tournaments/active — this PR ships before the backend
 *  workstream does (docs/LEAGUE-PIVOT-PLAN.md D5/D6). */
import { getTournament, getTournamentForRoute, WC26_FALLBACK } from "./tournament";
import { getActiveTournamentServer, getCompetitionTournamentServer } from "./api";
import type { ActiveTournament } from "./types";

jest.mock("./api");
const mockGet = getActiveTournamentServer as jest.MockedFunction<typeof getActiveTournamentServer>;
const mockScoped = getCompetitionTournamentServer as jest.MockedFunction<
  typeof getCompetitionTournamentServer
>;

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

/** OG cards render under /football/[comp]/..., so they must name the
 *  competition in the URL. getTournament() names whichever tournament is
 *  globally ACTIVE -- once UCL was activated that branded every World Cup
 *  share card "UEFA Champions League 2026-27". */
describe("getTournamentForRoute", () => {
  const WORLD_CUP: ActiveTournament = {
    id: 1,
    name: "FIFA World Cup 2026",
    year: 2026,
    format: "knockout",
    has_brackets: true,
  };
  const ACTIVE_UCL: ActiveTournament = {
    id: 5,
    name: "UEFA Champions League 2026-27",
    year: 2026,
    format: "league",
    has_brackets: false,
  };

  it("names the URL's competition, not whichever one is active", async () => {
    mockScoped.mockResolvedValue(WORLD_CUP);
    mockGet.mockResolvedValue(ACTIVE_UCL);

    expect(await getTournamentForRoute("wc26")).toEqual(WORLD_CUP);
    expect(mockScoped).toHaveBeenCalledWith("wc26");
    expect(mockGet).not.toHaveBeenCalled();
  });

  it("resolves each wired competition independently", async () => {
    mockScoped.mockResolvedValue(ACTIVE_UCL);
    expect(await getTournamentForRoute("ucl")).toEqual(ACTIVE_UCL);
    expect(mockScoped).toHaveBeenCalledWith("ucl");
  });

  it("keeps the active-tournament behaviour for a legacy route with no comp", async () => {
    mockGet.mockResolvedValue(ACTIVE_UCL);
    expect(await getTournamentForRoute(undefined)).toEqual(ACTIVE_UCL);
    expect(mockScoped).not.toHaveBeenCalled();
  });

  it("does not treat an unknown comp segment as a competition", async () => {
    mockGet.mockResolvedValue(ACTIVE_UCL);
    expect(await getTournamentForRoute("not-a-competition")).toEqual(ACTIVE_UCL);
    expect(mockScoped).not.toHaveBeenCalled();
  });
});
