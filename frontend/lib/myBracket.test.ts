import {
  groupTable, groupStageComplete, assignThirds, seedKnockouts,
  matchSides, champion, pruneKnockoutPicks, encodeBracket, decodeBracket,
  type BGroup, type GroupPicks, type KnockoutPicks,
} from "./myBracket";
import { R32, THIRD_SLOTS, FINAL_MATCH } from "./bracketStructure";

const LETTERS = "ABCDEFGHIJKL".split("");

/** 4 teams per group; round-robin 6 fixtures; strength A1>A2>A3>A4. */
function makeGroup(letter: string, startId: number): BGroup {
  const teams = [1, 2, 3, 4].map((n) => ({
    id: startId + n, name: `${letter}${n}`, strength: 1 - n * 0.1,
  }));
  const pairs: [number, number][] = [[0, 1], [2, 3], [0, 2], [1, 3], [0, 3], [1, 2]];
  const fixtures = pairs.map(([i, j], k) => ({
    matchId: startId * 10 + k, home: teams[i].name, away: teams[j].name,
  }));
  return { letter, teams, fixtures };
}

function fullTournament(): BGroup[] {
  return LETTERS.map((l, i) => makeGroup(l, (i + 1) * 100));
}

/** Pick the stronger (lower-numbered) team to win every fixture. */
function favouritesWin(groups: BGroup[]): GroupPicks {
  const picks: GroupPicks = {};
  for (const g of groups) {
    for (const fx of g.fixtures) {
      picks[fx.matchId] = fx.home < fx.away ? "home" : "away";
    }
  }
  return picks;
}

describe("groupTable", () => {
  const g = makeGroup("A", 100);

  it("awards 3/1/0 and ranks by points", () => {
    const table = groupTable(g, favouritesWin([g]));
    expect(table.map((r) => r.name)).toEqual(["A1", "A2", "A3", "A4"]);
    expect(table[0].points).toBe(9); // A1 wins all three
    expect(table[0].won).toBe(3);
  });

  it("breaks point ties by model strength", () => {
    // All draws -> everyone on 3 pts; order falls back to strength (A1>A2>A3>A4).
    const allDraws: GroupPicks = {};
    for (const fx of g.fixtures) allDraws[fx.matchId] = "draw";
    const table = groupTable(g, allDraws);
    expect(table.every((r) => r.points === 3)).toBe(true);
    expect(table.map((r) => r.name)).toEqual(["A1", "A2", "A3", "A4"]);
  });
});

describe("groupStageComplete", () => {
  it("is false until every fixture is picked, then true", () => {
    const groups = fullTournament();
    expect(groupStageComplete(groups, {})).toBe(false);
    expect(groupStageComplete(groups, favouritesWin(groups))).toBe(true);
  });
});

describe("assignThirds", () => {
  it("fills all 8 slots with distinct, eligible groups", () => {
    // A plausible set of 8 qualifying thirds.
    const qualifying = ["A", "B", "C", "D", "E", "F", "G", "H"];
    const a = assignThirds(qualifying);
    expect(Object.keys(a)).toHaveLength(8);
    const groupsUsed = Object.values(a);
    expect(new Set(groupsUsed).size).toBe(8); // distinct
    for (const slot of THIRD_SLOTS) {
      expect(slot.elig).toContain(a[slot.no]); // each respects eligibility
    }
  });
});

describe("seedKnockouts + knockout flow", () => {
  const groups = fullTournament();
  const picks = favouritesWin(groups);

  it("seeds all 16 Round-of-32 ties with two real teams", () => {
    const seeding = seedKnockouts(groups, picks);
    expect(Object.keys(seeding.r32)).toHaveLength(16);
    for (const tie of R32) {
      expect(seeding.r32[tie.no].a).toBeTruthy();
      expect(seeding.r32[tie.no].b).toBeTruthy();
      expect(seeding.r32[tie.no].a).not.toEqual(seeding.r32[tie.no].b);
    }
  });

  it("advances winners through to a champion", () => {
    const seeding = seedKnockouts(groups, picks);
    const ko: KnockoutPicks = {};
    // Always advance side A of each resolved match.
    const order = [...R32.map((m) => m.no), 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 104];
    for (const no of order) {
      const { a } = matchSides(no, seeding, ko);
      if (a) ko[no] = a;
    }
    expect(champion(ko)).toBeTruthy();
  });

  it("prunes downstream picks when an upstream pick changes", () => {
    const seeding = seedKnockouts(groups, picks);
    const tie = R32[0].no;
    const { a, b } = seeding.r32[tie];
    // User advanced A to the next round, then flips the R32 result to B.
    const feederMatch = Object.entries({ ...require("./bracketStructure").KO_TREE })
      .find(([, [f1, f2]]: any) => f1 === tie || f2 === tie)![0];
    const ko: KnockoutPicks = { [tie]: a, [Number(feederMatch)]: a };
    ko[tie] = b; // change upstream
    const cleaned = pruneKnockoutPicks(seeding, ko);
    expect(cleaned[Number(feederMatch)]).toBeUndefined(); // stale pick removed
    expect(cleaned[tie]).toBe(b);
  });
});

it("FINAL_MATCH is the title decider", () => {
  expect(FINAL_MATCH).toBe(104);
});

describe("share encode/decode", () => {
  const groups = fullTournament();

  it("round-trips group + knockout picks through a URL code", () => {
    const gp = favouritesWin(groups);
    const seeding = seedKnockouts(groups, gp);
    const ko: KnockoutPicks = {};
    for (const no of [...R32.map((m) => m.no), 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 104]) {
      const { a } = matchSides(no, seeding, ko);
      if (a) ko[no] = a;
    }
    const code = encodeBracket(groups, gp, ko);
    const back = decodeBracket(groups, code);
    expect(back.groupPicks).toEqual(gp);
    expect(back.koPicks).toEqual(ko);
    expect(champion(back.koPicks)).toBe(champion(ko));
  });

  it("round-trips a partial (group-only) bracket", () => {
    const gp = favouritesWin(groups);
    // drop one pick so the group stage is incomplete -> no knockout segment
    const firstId = groups[0].fixtures[0].matchId;
    delete (gp as GroupPicks)[firstId];
    const back = decodeBracket(groups, encodeBracket(groups, gp, {}));
    expect(back.groupPicks).toEqual(gp);
    expect(back.koPicks).toEqual({});
  });

  it("ignores a malformed code without throwing", () => {
    expect(() => decodeBracket(groups, "not-a-real-code")).not.toThrow();
  });
});
