import { zoneForRank, zoneToneClasses } from "@/lib/standingsZones";
import type { StandingsZone } from "@/lib/sports";

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
