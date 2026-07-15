import {
  finishedRounds,
  isNrlLiveNow,
  liveNow,
  NRL_LIVE_WINDOW_MINUTES,
  upcomingRounds,
} from "@/lib/nrlLive";
import type { NrlMatch, NrlRound } from "@/lib/types";

const NOW = new Date("2026-07-18T07:00:00Z");

function match(over: Partial<NrlMatch>): NrlMatch {
  return {
    match_no: 1, kickoff_utc: null, venue: null, home: "A", away: "B",
    home_team_id: 1, away_team_id: 2, score_home: null, score_away: null,
    status: "scheduled", prediction: null, ...over,
  } as NrlMatch;
}

describe("isNrlLiveNow", () => {
  it("is live from kickoff until the window closes", () => {
    const m = match({ kickoff_utc: "2026-07-18T06:00:00Z" }); // 60 min ago
    expect(isNrlLiveNow(m, NOW)).toBe(true);
  });
  it("is not live before kickoff, after the window, when finished, or undated", () => {
    expect(isNrlLiveNow(match({ kickoff_utc: "2026-07-18T08:00:00Z" }), NOW)).toBe(false);
    const stale = new Date(NOW.getTime() + (NRL_LIVE_WINDOW_MINUTES + 1) * 60_000);
    expect(isNrlLiveNow(match({ kickoff_utc: "2026-07-18T07:00:00Z" }), stale)).toBe(false);
    expect(isNrlLiveNow(match({ kickoff_utc: "2026-07-18T06:00:00Z", status: "finished" }), NOW)).toBe(false);
    expect(isNrlLiveNow(match({}), NOW)).toBe(false);
  });
});

const ROUNDS: NrlRound[] = [
  { round: 19, matches: [
    match({ match_no: 1, status: "finished", kickoff_utc: "2026-07-11T05:00:00Z", score_home: 6, score_away: 32 }),
    match({ match_no: 2, status: "finished", kickoff_utc: "2026-07-12T05:00:00Z", score_home: 22, score_away: 18 }),
  ]},
  { round: 20, matches: [
    match({ match_no: 3, status: "scheduled", kickoff_utc: "2026-07-18T06:30:00Z" }), // in window (30 min ago)
    match({ match_no: 4, status: "scheduled", kickoff_utc: "2026-07-18T09:35:00Z" }),
    match({ match_no: 5, status: "scheduled", kickoff_utc: "2026-07-19T04:00:00Z" }),
  ]},
  { round: 21, matches: [
    match({ match_no: 6, status: "scheduled", kickoff_utc: "2026-07-23T09:50:00Z" }),
  ]},
];

describe("grouping", () => {
  it("liveNow returns only in-window matches, tagged with their round", () => {
    expect(liveNow(ROUNDS, NOW)).toEqual([
      { round: 20, match: expect.objectContaining({ match_no: 3 }) },
    ]);
  });
  it("upcomingRounds excludes live + finished, round asc, kickoff asc", () => {
    const groups = upcomingRounds(ROUNDS, NOW);
    expect(groups.map((g) => g.round)).toEqual([20, 21]);
    expect(groups[0].matches.map((m) => m.match_no)).toEqual([4, 5]);
  });
  it("finishedRounds is round desc, kickoff desc within", () => {
    const groups = finishedRounds(ROUNDS);
    expect(groups.map((g) => g.round)).toEqual([19]);
    expect(groups[0].matches.map((m) => m.match_no)).toEqual([2, 1]);
  });
  it("drops empty groups", () => {
    expect(finishedRounds([{ round: 22, matches: [match({})] }])).toEqual([]);
  });
});
