import {
  SPORTS,
  sportFromPathname,
  switchSportHref,
  COMPETITIONS,
  competitionFromPathname,
  isCompetitionHomeHref,
  isWiredCompetition,
  isWiredFootballCompetition,
  competitionsForSport,
  isCompetitionId,
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

  it("keeps the Play hub as the shared destination when switching sports", () => {
    // Floodlight P5: the old /tips <-> /nrl/tips equivalence folded into one
    // /play <-> /play row, so switching sport on the hub stays on the hub.
    expect(switchSportHref("/play", "nrl")).toBe("/play");
    expect(switchSportHref("/play", "football")).toBe("/play");
    // The old tips routes stay live but are no longer sport-equivalents, so
    // switching sport from them falls back to the target sport's home.
    expect(switchSportHref("/tips", "nrl")).toBe("/nrl");
  });

  // Legacy SPORTS structure kept as a compat export (see lib/sports.ts) -- its
  // nav-link shape still matches football/NRL, so this label assertion still
  // holds. The registry equivalents (source of truth for SiteNav/BottomNav as
  // of Floodlight P1 slice p1-s4) live under "competition registry" below.
  it("gives football and NRL their nav links with the shared Play tab (P5)", () => {
    expect(SPORTS.football.navLinks.map((l) => l.label)).toEqual(
      ["Home", "Matches", "Groups", "Play", "You"]);
    expect(SPORTS.nrl.navLinks.map((l) => l.label)).toEqual(
      ["Home", "Matches", "Ladder", "Record", "Play"]);
    // Play subsumes the old mutually-exclusive Bracket/Tips slot -- neither is
    // a separate nav entry anymore, and each sport stays at five tabs.
    for (const sport of [SPORTS.football, SPORTS.nrl]) {
      expect(sport.navLinks).toHaveLength(5);
      expect(sport.navLinks.find((l) => l.label === "Play")?.href).toBe("/play");
      expect(sport.navLinks.some((l) => l.label === "Bracket" || l.label === "Tips")).toBe(false);
    }
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

  // Regression: the /football/[comp]/... route wrappers must reject nrl --
  // it's a wired competition (isWiredCompetition("nrl") === true above) but
  // its basePath is /nrl, not /football/nrl, so isWiredCompetition alone let
  // /football/nrl and its subroutes 200 with WC26 content instead of 404ing.
  it("scopes isWiredFootballCompetition to the football namespace, rejecting nrl", () => {
    expect(isWiredFootballCompetition("wc26")).toBe(true);
    expect(isWiredFootballCompetition("nrl")).toBe(false);
    expect(isWiredFootballCompetition("epl")).toBe(false); // P1: not enabled yet
    expect(isWiredFootballCompetition("bogus")).toBe(false);
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

  // Floodlight P1 slice p1-s4: SiteNav/BottomNav now derive their links from
  // COMPETITIONS[competitionFromPathname(...)] instead of SPORTS[sportFromPathname(...)] --
  // these are the registry equivalents of the old SPORTS.football/SPORTS.nrl
  // nav-link assertions above.
  it("gives wc26 and nrl their nav links with the shared Play tab (P5)", () => {
    expect(COMPETITIONS.wc26.navLinks.map((l) => l.label)).toEqual(
      ["Home", "Fixtures", "Groups", "Play", "You"]);
    expect(COMPETITIONS.nrl.navLinks.map((l) => l.label)).toEqual(
      ["Home", "Matches", "Ladder", "Record", "Play"]);
  });

  it("folds wc26's Bracket + Tips into one always-on Play tab (P5)", () => {
    const playLink = COMPETITIONS.wc26.navLinks.find((l) => l.label === "Play");
    expect(playLink?.href).toBe("/play");
    // Play lights up on the routes it subsumes -- both /tips and /brackets stay live.
    expect(playLink?.activePrefixes).toEqual(["/tips", "/brackets"]);
    // The separate Bracket/Tips entries (and their format guards) are gone.
    expect(
      COMPETITIONS.wc26.navLinks.some((l) => l.label === "Bracket" || l.label === "Tips"),
    ).toBe(false);
    expect(
      COMPETITIONS.wc26.navLinks.some((l) => l.requiresBrackets || l.requiresLeagueFormat),
    ).toBe(false);
  });

  it("gives NRL a Play tab that lights on /nrl/tips, not a You/leaderboard slot", () => {
    const playLink = COMPETITIONS.nrl.navLinks.find((l) => l.label === "Play");
    expect(playLink?.href).toBe("/play");
    expect(playLink?.activePrefixes).toEqual(["/nrl/tips"]);
    expect(COMPETITIONS.nrl.navLinks.find((l) => l.label === "You")).toBeUndefined();
    expect(COMPETITIONS.nrl.navLinks.find((l) => l.label === "Tips")).toBeUndefined();
  });

  it("caps every competition at five nav entries, each with a Play tab and no Bracket/Tips", () => {
    for (const comp of Object.values(COMPETITIONS)) {
      expect(comp.navLinks.length).toBeLessThanOrEqual(5);
      expect(comp.navLinks.find((l) => l.label === "Play")?.href).toBe("/play");
      expect(comp.navLinks.some((l) => l.label === "Bracket" || l.label === "Tips")).toBe(false);
    }
  });

  it("recognizes competition home hrefs for the nav components' exact-match active state", () => {
    expect(isCompetitionHomeHref("/football/wc26")).toBe(true);
    expect(isCompetitionHomeHref("/nrl")).toBe(true);
    expect(isCompetitionHomeHref("/football/wc26/fixtures")).toBe(false);
  });

  // Floodlight P1 slice p1-s5: validates a localStorage-read pin (lib/competitionPrefs.ts)
  // before trusting it as a CompetitionId.
  it("validates a string against the competition registry via isCompetitionId", () => {
    expect(isCompetitionId("wc26")).toBe(true);
    expect(isCompetitionId("nope")).toBe(false);
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
