import {
  SPORTS,
  sportFromPathname,
  switchSportHref,
  COMPETITIONS,
  competitionFromPathname,
  isWiredCompetition,
  competitionsForSport,
} from "@/lib/sports";

describe("sport config", () => {
  it("detects the active sport from the pathname prefix", () => {
    expect(sportFromPathname("/")).toBe("football");
    expect(sportFromPathname("/matches")).toBe("football");
    expect(sportFromPathname("/nrl")).toBe("nrl");
    expect(sportFromPathname("/nrl/ladder")).toBe("nrl");
    expect(sportFromPathname("/nrlx")).toBe("football"); // prefix must be exact
  });

  it("maps to the equivalent page when switching, else the sport home", () => {
    expect(switchSportHref("/matches", "nrl")).toBe("/nrl/matches");
    expect(switchSportHref("/nrl/matches", "football")).toBe("/matches");
    expect(switchSportHref("/groups", "nrl")).toBe("/nrl"); // no NRL groups
    expect(switchSportHref("/nrl/ladder", "football")).toBe("/");
    expect(switchSportHref("/", "nrl")).toBe("/nrl");
  });

  it("maps the leaderboard (You) page between sports so context is preserved", () => {
    expect(switchSportHref("/leaderboard", "nrl")).toBe("/nrl/leaderboard");
    expect(switchSportHref("/nrl/leaderboard", "football")).toBe("/leaderboard");
  });

  it("maps the tips page between sports so context is preserved", () => {
    expect(switchSportHref("/tips", "nrl")).toBe("/nrl/tips");
    expect(switchSportHref("/nrl/tips", "football")).toBe("/tips");
  });

  it("gives football and NRL their nav links (Tips only renders once its format guard is met)", () => {
    expect(SPORTS.football.navLinks.map((l) => l.label)).toEqual(
      ["Home", "Matches", "Groups", "Bracket", "You", "Tips"]);
    expect(SPORTS.nrl.navLinks.map((l) => l.label)).toEqual(
      ["Home", "Matches", "Ladder", "Record", "Tips"]);
  });

  it("gives football's Tips link a requiresLeagueFormat guard so it and Bracket never both show", () => {
    const tipsLink = SPORTS.football.navLinks.find((l) => l.label === "Tips");
    expect(tipsLink?.href).toBe("/tips");
    expect(tipsLink?.requiresLeagueFormat).toBe(true);
    const bracketLink = SPORTS.football.navLinks.find((l) => l.label === "Bracket");
    expect(bracketLink?.requiresBrackets).toBe(true);
  });

  it("gives NRL a Tips link to the tipsheet (design doc: NRL Round Tips) instead of the You/leaderboard slot", () => {
    const tipsLink = SPORTS.nrl.navLinks.find((l) => l.label === "Tips");
    expect(tipsLink?.href).toBe("/nrl/tips");
    expect(SPORTS.nrl.navLinks.find((l) => l.label === "You")).toBeUndefined();
  });

  it("recognizes /nrl/leaderboard as NRL context", () => {
    expect(sportFromPathname("/nrl/leaderboard")).toBe("nrl");
  });
});

describe("competition registry", () => {
  it("resolves the active competition from the pathname, longest basePath wins", () => {
    expect(competitionFromPathname("/football/epl/fixtures")).toBe("epl");
    expect(competitionFromPathname("/football/wc26")).toBe("wc26");
    expect(competitionFromPathname("/football/wc26/match/42")).toBe("wc26");
    expect(competitionFromPathname("/nrl/ladder")).toBe("nrl");
  });

  it("falls back to the DEFAULT_COMPETITION for un-namespaced/global routes", () => {
    expect(competitionFromPathname("/")).toBe("wc26");
    expect(competitionFromPathname("/leaderboard")).toBe("wc26");
    expect(competitionFromPathname("/tips")).toBe("wc26");
  });

  it("gates disabled/unknown competitions via isWiredCompetition", () => {
    expect(isWiredCompetition("wc26")).toBe(true);
    expect(isWiredCompetition("nrl")).toBe(true);
    expect(isWiredCompetition("epl")).toBe(false); // P1: not enabled yet
    expect(isWiredCompetition("bogus")).toBe(false);
  });

  it("gives wc26 its knockout shape (bracket + groups)", () => {
    expect(COMPETITIONS.wc26.hasBracket).toBe(true);
    expect(COMPETITIONS.wc26.hasGroups).toBe(true);
    expect(COMPETITIONS.epl.format).toBe("league");
    expect(COMPETITIONS.epl.hasBracket).toBe(false);
  });

  it("gives each sport its own terminology (Fixtures/Standings vs Matches/Ladder)", () => {
    expect(COMPETITIONS.nrl.terms).toEqual({ fixtures: "Matches", standings: "Ladder" });
    expect(COMPETITIONS.epl.terms.fixtures).toBe("Fixtures");
  });

  it("lists competitions per sport in stable display order", () => {
    expect(competitionsForSport("football").map((c) => c.id)).toEqual([
      "epl",
      "laliga",
      "bundesliga",
      "wc26",
    ]);
    expect(competitionsForSport("nrl").map((c) => c.id)).toEqual(["nrl"]);
  });

  it("gives every competition its own accent token", () => {
    expect(COMPETITIONS.epl.accentVar).toBe("--accent-epl");
  });
});

// Floodlight P1 slice p1-s3: the /football/[comp]/... route wrappers and the
// next.config.mjs legacy redirects both hard-code "/football/wc26/..." as
// their destination. These assertions guard that string against drift -- if
// COMPETITIONS.wc26.basePath ever changes, this fails loudly instead of the
// redirects quietly 404ing.
describe("wc26 route wiring (guards the redirect destinations)", () => {
  it("wires wc26 as an enabled competition at the expected basePath", () => {
    expect(isWiredCompetition("wc26")).toBe(true);
    expect(COMPETITIONS.wc26.basePath).toBe("/football/wc26");
  });

  it.each([
    "/football/wc26/fixtures",
    "/football/wc26/match/9",
    "/football/wc26/groups",
    "/football/wc26/bracket",
    "/football/wc26/team/3",
  ])("resolves %s to the wc26 competition", (pathname) => {
    expect(competitionFromPathname(pathname)).toBe("wc26");
  });
});
