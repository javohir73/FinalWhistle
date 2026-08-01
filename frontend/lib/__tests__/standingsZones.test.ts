import { zoneForRank, zoneToneClasses } from "@/lib/standingsZones";
import { COMPETITIONS, type StandingsZone } from "@/lib/sports";

const EPL_ZONES: StandingsZone[] = [
  { from: 1, to: 4, label: "Champions League", tone: "cl" },
  { from: 5, to: 5, label: "Europa League", tone: "europa" },
  { from: 18, to: 20, label: "Relegation", tone: "releg" },
];

describe("zoneForRank", () => {
  it("hits the cl zone at both boundary ranks", () => {
    expect(zoneForRank(EPL_ZONES, 1)?.tone).toBe("cl");
    expect(zoneForRank(EPL_ZONES, 4)?.tone).toBe("cl");
  });

  it("misses cl and hits europa just past the boundary", () => {
    expect(zoneForRank(EPL_ZONES, 5)?.tone).toBe("europa");
  });

  it("hits the relegation band across its full range", () => {
    expect(zoneForRank(EPL_ZONES, 18)?.tone).toBe("releg");
    expect(zoneForRank(EPL_ZONES, 19)?.tone).toBe("releg");
    expect(zoneForRank(EPL_ZONES, 20)?.tone).toBe("releg");
  });

  it("returns null outside every band", () => {
    expect(zoneForRank(EPL_ZONES, 10)).toBeNull();
    expect(zoneForRank(EPL_ZONES, 21)).toBeNull();
    expect(zoneForRank([], 1)).toBeNull();
  });
});

describe("zoneToneClasses", () => {
  it("maps cl to the win (lime) treatment", () => {
    expect(zoneToneClasses("cl").stripe).toContain("win");
  });

  it("maps releg to the loss (rose) treatment", () => {
    expect(zoneToneClasses("releg").stripe).toContain("loss");
  });

  it("maps none to all-empty classes", () => {
    expect(zoneToneClasses("none")).toEqual({ stripe: "", bg: "", rankText: "" });
  });
});

describe("competition standings zones", () => {
  it("uses Bundesliga's 18-team relegation playoff and direct-drop bands", () => {
    const zones = COMPETITIONS.bundesliga.zones;

    expect(zoneForRank(zones, 15)).toBeNull();
    expect(zoneForRank(zones, 16)?.label).toBe("Relegation playoff");
    expect(zoneForRank(zones, 17)?.label).toBe("Relegation");
    expect(zoneForRank(zones, 18)?.label).toBe("Relegation");
    expect(zoneForRank(zones, 19)).toBeNull();
  });

  it("keeps La Liga's 20-team relegation band", () => {
    const zones = COMPETITIONS.laliga.zones;

    expect(zoneForRank(zones, 17)).toBeNull();
    expect(zoneForRank(zones, 18)?.label).toBe("Relegation");
    expect(zoneForRank(zones, 20)?.label).toBe("Relegation");
  });

  it("uses the Champions League's league-phase qualification bands", () => {
    const zones = COMPETITIONS.ucl.zones;

    expect(zoneForRank(zones, 1)?.label).toBe("Round of 16");
    expect(zoneForRank(zones, 8)?.label).toBe("Round of 16");
    expect(zoneForRank(zones, 9)?.label).toBe("Knockout phase play-offs");
    expect(zoneForRank(zones, 24)?.label).toBe("Knockout phase play-offs");
    expect(zoneForRank(zones, 25)).toBeNull();
  });
});
