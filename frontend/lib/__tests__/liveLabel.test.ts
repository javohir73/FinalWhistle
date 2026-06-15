import { liveLabel, isLiveNow, MAX_LIVE_MINUTES } from "@/lib/liveLabel";
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

describe("isLiveNow", () => {
  const now = new Date("2026-06-15T07:00:00Z");
  const ko = (minsAgo: number) =>
    new Date(now.getTime() - minsAgo * 60_000).toISOString();

  it("is live for an in_play match that kicked off within the window", () => {
    expect(isLiveNow({ status: "in_play", kickoff_utc: ko(60) }, now)).toBe(true);
    expect(isLiveNow({ status: "in_play", kickoff_utc: ko(MAX_LIVE_MINUTES) }, now)).toBe(true);
  });

  it("is NOT live for an in_play match stranded past the window (the stuck-90' bug)", () => {
    // Ivory Coast vs Ecuador: in_play but kicked off ~8h ago because the live
    // refresh stalled — must read as over, not "LIVE 90'".
    expect(isLiveNow({ status: "in_play", kickoff_utc: ko(478) }, now)).toBe(false);
    expect(isLiveNow({ status: "in_play", kickoff_utc: ko(MAX_LIVE_MINUTES + 1) }, now)).toBe(false);
  });

  it("is never live for scheduled or finished matches", () => {
    expect(isLiveNow({ status: "scheduled", kickoff_utc: ko(10) }, now)).toBe(false);
    expect(isLiveNow({ status: "finished", kickoff_utc: ko(60) }, now)).toBe(false);
  });

  it("trusts the feed when there is no kickoff time to bound by", () => {
    expect(isLiveNow({ status: "in_play", kickoff_utc: null }, now)).toBe(true);
  });
});
