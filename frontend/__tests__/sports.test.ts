import { SPORTS, sportFromPathname, switchSportHref } from "@/lib/sports";

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

  it("keeps football nav unchanged and gives NRL its five links", () => {
    expect(SPORTS.football.navLinks.map((l) => l.label)).toEqual(
      ["Home", "Matches", "Groups", "Bracket", "You"]);
    expect(SPORTS.nrl.navLinks.map((l) => l.label)).toEqual(
      ["Home", "Matches", "Ladder", "Record", "Tips"]);
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
