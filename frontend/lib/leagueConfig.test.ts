import { ACTIVE_LEAGUES, DEFAULT_LEAGUE, leagueLabel } from "./leagueConfig";

it("labels every active league correctly", () => {
  expect(leagueLabel("epl")).toBe("Premier League");
  expect(leagueLabel("laliga")).toBe("La Liga");
  expect(leagueLabel("bundesliga")).toBe("Bundesliga");
  expect(leagueLabel("ucl")).toBe("UEFA Champions League");
});

it("falls back to an uppercased code for an unregistered league", () => {
  expect(leagueLabel("seriea")).toBe("SERIEA");
});

it("offers every active football league in pipeline order", () => {
  expect(ACTIVE_LEAGUES).toEqual(["epl", "laliga", "bundesliga"]);
  expect(DEFAULT_LEAGUE).toBe("epl");
});
