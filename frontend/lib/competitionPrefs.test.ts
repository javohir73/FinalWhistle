import {
  readPinnedCompetition,
  writePinnedCompetition,
  clearPinnedCompetition,
} from "@/lib/competitionPrefs";

beforeEach(() => {
  window.localStorage.clear();
});

describe("competition pin prefs", () => {
  it("returns null when nothing is stored", () => {
    expect(readPinnedCompetition()).toBeNull();
  });

  it("round-trips a pinned competition through localStorage", () => {
    writePinnedCompetition("epl");
    expect(readPinnedCompetition()).toBe("epl");
  });

  it("rejects a stored value that isn't a known competition id", () => {
    window.localStorage.setItem("fw_pinned_comp", "bogus");
    expect(readPinnedCompetition()).toBeNull();
  });

  it("clears the pin", () => {
    writePinnedCompetition("nrl");
    clearPinnedCompetition();
    expect(readPinnedCompetition()).toBeNull();
  });
});
