import { ACTIVE_LEAGUES, DEFAULT_LEAGUE, leagueLabel } from "./leagueConfig";

it("labels every registered league correctly, including ones not yet active", () => {
  expect(leagueLabel("epl")).toBe("Premier League");
  expect(leagueLabel("laliga")).toBe("La Liga");
  expect(leagueLabel("bundesliga")).toBe("Bundesliga");
});

it("falls back to an uppercased code for an unregistered league", () => {
  expect(leagueLabel("seriea")).toBe("SERIEA");
});

it("keeps the switcher EPL-only until a second league actually goes active", () => {
  expect(ACTIVE_LEAGUES).toEqual(["epl"]);
  expect(DEFAULT_LEAGUE).toBe("epl");
});
