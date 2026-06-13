import { liveLabel } from "@/lib/liveLabel";
import type { MatchSummary } from "@/lib/types";

const s = (over: Partial<MatchSummary>): MatchSummary =>
  ({
    status: "in_play",
    minute: null,
    period: "first_half",
    injury_time: null,
    penalty_home: null,
    penalty_away: null,
    ...over,
  } as MatchSummary);

describe("liveLabel", () => {
  it("shows the running minute in open play", () => {
    expect(liveLabel(s({ period: "second_half", minute: 57 }))).toBe("57'");
  });

  it("shows stoppage time as 45+2' / 90+5'", () => {
    expect(liveLabel(s({ period: "first_half", minute: 45, injury_time: 2 }))).toBe("45+2'");
    expect(liveLabel(s({ period: "second_half", minute: 90, injury_time: 5 }))).toBe("90+5'");
  });

  it("freezes at half-time", () => {
    expect(liveLabel(s({ period: "half_time", minute: null }))).toBe("HT");
  });

  it("labels extra time, with the minute when the feed provides it", () => {
    expect(liveLabel(s({ period: "extra_time", minute: 105 }))).toBe("ET 105'");
    expect(liveLabel(s({ period: "extra_time", minute: 90 }))).toBe("ET"); // free-tier estimate caps at 90
  });

  it("labels a penalty shootout", () => {
    expect(liveLabel(s({ period: "penalty_shootout", minute: null }))).toBe("PENS");
  });

  it("shows FT at full time regardless of period", () => {
    expect(liveLabel(s({ status: "finished", period: null, minute: null }))).toBe("FT");
  });

  it("is empty before kickoff", () => {
    expect(liveLabel(s({ status: "scheduled", period: null }))).toBe("");
  });

  it("falls back to LIVE when in play but the minute is unknown", () => {
    expect(liveLabel(s({ period: "first_half", minute: null }))).toBe("LIVE");
  });
});
