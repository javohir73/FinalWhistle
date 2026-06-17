import { groupHasLiveMatch } from "./liveLabel";
import type { MatchSummary } from "./types";

type LiveFields = Pick<MatchSummary, "group" | "status" | "kickoff_utc">;

const NOW = new Date("2026-06-18T12:00:00Z");

function match(over: Partial<LiveFields>): LiveFields {
  return {
    group: "Group A",
    status: "scheduled",
    kickoff_utc: NOW.toISOString(),
    ...over,
  };
}

describe("groupHasLiveMatch", () => {
  it("is true when a match in the group is in play and kicked off recently", () => {
    const matches = [
      match({ group: "Group A", status: "in_play", kickoff_utc: "2026-06-18T11:30:00Z" }),
    ];
    expect(groupHasLiveMatch("Group A", matches, NOW)).toBe(true);
  });

  it("is false when no matches are provided", () => {
    expect(groupHasLiveMatch("Group A", undefined, NOW)).toBe(false);
  });

  it("ignores live matches that belong to a different group", () => {
    const matches = [
      match({ group: "Group B", status: "in_play", kickoff_utc: "2026-06-18T11:30:00Z" }),
    ];
    expect(groupHasLiveMatch("Group A", matches, NOW)).toBe(false);
  });

  it("is false when the group's matches are scheduled or finished", () => {
    const matches = [
      match({ group: "Group A", status: "scheduled" }),
      match({ group: "Group A", status: "finished" }),
    ];
    expect(groupHasLiveMatch("Group A", matches, NOW)).toBe(false);
  });

  it("is false when an in-play match kicked off too long ago (stale feed)", () => {
    const matches = [
      // 4 hours before NOW — past MAX_LIVE_MINUTES (180)
      match({ group: "Group A", status: "in_play", kickoff_utc: "2026-06-18T08:00:00Z" }),
    ];
    expect(groupHasLiveMatch("Group A", matches, NOW)).toBe(false);
  });
});
