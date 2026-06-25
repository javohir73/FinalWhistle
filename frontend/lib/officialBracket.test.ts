import { buildTree, resolveSlotLabel, resolveWinner } from "./officialBracket";
import { THIRD_PLACE } from "./bracketStructure";
import type { KnockoutTie } from "./types";

function tie(over: Partial<KnockoutTie>): KnockoutTie {
  return {
    match_no: 89,
    match_id: 1,
    stage: "R16",
    status: "scheduled",
    kickoff_utc: null,
    home: { team_id: null, team: null, score: null, penalty: null },
    away: { team_id: null, team: null, score: null, penalty: null },
    minute: null,
    period: null,
    injury_time: null,
    ...over,
  };
}

describe("resolveSlotLabel", () => {
  it("renders R32 placement sides as <pos><group>", () => {
    expect(resolveSlotLabel(73, "a")).toBe("2A");
    expect(resolveSlotLabel(73, "b")).toBe("2B");
    expect(resolveSlotLabel(75, "a")).toBe("1F");
    expect(resolveSlotLabel(88, "b")).toBe("2G");
  });

  it("renders R32 third-place sides as 3-<sorted elig>", () => {
    expect(resolveSlotLabel(74, "b")).toBe("3-ABCDF");
    expect(resolveSlotLabel(77, "b")).toBe("3-CDFGH");
    expect(resolveSlotLabel(87, "b")).toBe("3-DEIJL");
  });

  it("resolves downstream feeders to 'Winner <feeder>'", () => {
    expect(resolveSlotLabel(89, "a")).toBe("Winner 74");
    expect(resolveSlotLabel(89, "b")).toBe("Winner 77");
    expect(resolveSlotLabel(104, "a")).toBe("Winner 101");
    expect(resolveSlotLabel(104, "b")).toBe("Winner 102");
  });

  it("resolves 103 via THIRD_PLACE loser feeders, never KO_TREE", () => {
    expect(resolveSlotLabel(THIRD_PLACE.no, "a")).toBe("Loser 101");
    expect(resolveSlotLabel(THIRD_PLACE.no, "b")).toBe("Loser 102");
  });
});

describe("resolveWinner", () => {
  it("returns null when not finished", () => {
    expect(resolveWinner(tie({ status: "in_play", home: { team_id: 1, team: "A", score: 2, penalty: null }, away: { team_id: 2, team: "B", score: 1, penalty: null } }))).toBeNull();
  });

  it("picks the higher score when finished", () => {
    expect(resolveWinner(tie({ status: "finished", home: { team_id: 1, team: "A", score: 2, penalty: null }, away: { team_id: 2, team: "B", score: 1, penalty: null } }))).toBe("a");
  });

  it("AET 1-2 picks away by score", () => {
    expect(resolveWinner(tie({ status: "finished", period: "extra_time", home: { team_id: 1, team: "A", score: 1, penalty: null }, away: { team_id: 2, team: "B", score: 2, penalty: null } }))).toBe("b");
  });

  it("1-1 with penalties 4-2 picks home", () => {
    expect(resolveWinner(tie({ status: "finished", home: { team_id: 1, team: "A", score: 1, penalty: 4 }, away: { team_id: 2, team: "B", score: 1, penalty: 2 } }))).toBe("a");
  });

  it("0-0 with penalties 3-3 is undecided", () => {
    expect(resolveWinner(tie({ status: "finished", home: { team_id: 1, team: "A", score: 0, penalty: 3 }, away: { team_id: 2, team: "B", score: 0, penalty: 3 } }))).toBeNull();
  });
});

describe("buildTree", () => {
  it("null bracket yields a full label-only tree", () => {
    const tree = buildTree(null);
    expect(tree[89].state).toBe("labels");
    expect(tree[89].a.label).toBe("Winner 74");
    expect(tree[89].matchId).toBeNull();
    expect(tree[103].round).toBe("third");
    expect(tree[103].a.label).toBe("Loser 101");
    expect(tree[104].round).toBe("final");
    expect(Object.keys(tree)).toHaveLength(32); // 73..104
  });

  it("overlays real teams and marks winner + penalty text on a finished tie", () => {
    const tree = buildTree({
      ties: [
        tie({
          match_no: 89,
          match_id: 312,
          stage: "R16",
          status: "finished",
          home: { team_id: 44, team: "Argentina", score: 1, penalty: 4 },
          away: { team_id: 51, team: "France", score: 1, penalty: 2 },
        }),
      ],
    });
    const v = tree[89];
    expect(v.state).toBe("finished");
    expect(v.matchId).toBe(312);
    expect(v.a.team).toBe("Argentina");
    expect(v.a.isWinner).toBe(true);
    expect(v.b.isWinner).toBe(false);
    expect(v.penaltyText).toBe("(4-2 pens)");
    expect(v.liveLabel).toBe("FT");
  });

  it("renders a mixed tie: real team on A, slot label on B", () => {
    const tree = buildTree({
      ties: [
        tie({
          match_no: 90,
          match_id: 320,
          stage: "R16",
          status: "scheduled",
          home: { team_id: 44, team: "Argentina", score: null, penalty: null },
          away: { team_id: null, team: null, score: null, penalty: null },
        }),
      ],
    });
    const v = tree[90];
    expect(v.state).toBe("scheduled");
    expect(v.a.team).toBe("Argentina");
    expect(v.b.team).toBeNull();
    expect(v.b.label).toBe("Winner 75");
  });

  it("emits in_play liveLabel and ET label", () => {
    const tree = buildTree({
      ties: [
        tie({
          match_no: 91,
          match_id: 330,
          stage: "R16",
          status: "in_play",
          period: "extra_time",
          minute: 105,
          home: { team_id: 44, team: "A", score: 1, penalty: null },
          away: { team_id: 51, team: "B", score: 1, penalty: null },
        }),
      ],
    });
    expect(tree[91].state).toBe("in_play");
    expect(tree[91].liveLabel).toBe("ET 105'");
  });
});
