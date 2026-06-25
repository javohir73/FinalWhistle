/** Pure, React-free logic for the official knockout bracket tree.
 *  Maps KO Match rows (or pure topology when null) to renderable TieViews:
 *  slot-label resolution, node-state derivation, penalties-aware winner read. */
import { R32, THIRD_SLOTS, KO_TREE, THIRD_PLACE } from "./bracketStructure";
import { liveLabel } from "./liveLabel";
import type { KnockoutBracket, KnockoutTie } from "./types";

export type TieState = "labels" | "scheduled" | "in_play" | "finished";

export type SideView = {
  teamId: number | null;
  team: string | null;
  label: string;
  score: number | null;
  penalty: number | null;
  isWinner: boolean;
};

export type TieView = {
  matchNo: number;
  matchId: number | null;
  round: "r32" | "r16" | "qf" | "sf" | "final" | "third";
  state: TieState;
  a: SideView;
  b: SideView;
  liveLabel: string;
  penaltyText: string | null;
};

const R16_NOS = [89, 90, 91, 92, 93, 94, 95, 96];
const QF_NOS = [97, 98, 99, 100];
const SF_NOS = [101, 102];

/** All KO match numbers in render order, 73..104 (including 103). */
const ALL_NOS: number[] = [
  ...R32.map((m) => m.no),
  ...R16_NOS,
  ...QF_NOS,
  ...SF_NOS,
  THIRD_PLACE.no,
  104,
];

function roundOf(matchNo: number): TieView["round"] {
  if (matchNo === THIRD_PLACE.no) return "third";
  if (matchNo === 104) return "final";
  if (SF_NOS.includes(matchNo)) return "sf";
  if (QF_NOS.includes(matchNo)) return "qf";
  if (R16_NOS.includes(matchNo)) return "r16";
  return "r32";
}

/** A side's slot label from R32 placements / THIRD_SLOTS / KO_TREE / THIRD_PLACE. */
export function resolveSlotLabel(matchNo: number, side: "a" | "b"): string {
  if (matchNo === THIRD_PLACE.no) {
    const feeder = THIRD_PLACE.loserFeeders[side === "a" ? 0 : 1];
    return `Loser ${feeder}`;
  }
  const r32 = R32.find((m) => m.no === matchNo);
  if (r32) {
    const slot = side === "a" ? r32.a : r32.b;
    if ("third" in slot) {
      const t = THIRD_SLOTS.find((s) => s.no === matchNo);
      const letters = t ? [...t.elig].sort().join("") : "";
      return `3-${letters}`;
    }
    return `${slot.pos}${slot.g}`;
  }
  const feeders = KO_TREE[matchNo];
  if (feeders) return `Winner ${feeders[side === "a" ? 0 : 1]}`;
  return "";
}

/** Winner: score first, then penalties; null until finished / still undecided. */
export function resolveWinner(tie: KnockoutTie): "a" | "b" | null {
  if (tie.status !== "finished") return null;
  const { home, away } = tie;
  if (home.score != null && away.score != null) {
    if (home.score > away.score) return "a";
    if (away.score > home.score) return "b";
  }
  if (home.penalty != null && away.penalty != null) {
    if (home.penalty > away.penalty) return "a";
    if (away.penalty > home.penalty) return "b";
  }
  return null;
}

function side(
  raw: KnockoutTie["home"] | null,
  matchNo: number,
  which: "a" | "b",
  isWinner: boolean,
): SideView {
  return {
    teamId: raw?.team_id ?? null,
    team: raw?.team ?? null,
    label: resolveSlotLabel(matchNo, which),
    score: raw?.score ?? null,
    penalty: raw?.penalty ?? null,
    isWinner,
  };
}

function viewFor(matchNo: number, tie: KnockoutTie | undefined): TieView {
  const round = roundOf(matchNo);
  if (!tie) {
    return {
      matchNo,
      matchId: null,
      round,
      state: "labels",
      a: side(null, matchNo, "a", false),
      b: side(null, matchNo, "b", false),
      liveLabel: "",
      penaltyText: null,
    };
  }
  const winner = resolveWinner(tie);
  const hasTeam = tie.home.team_id != null || tie.away.team_id != null;
  const state: TieState = !hasTeam ? "labels" : tie.status;
  const penaltyText =
    tie.status === "finished" &&
    tie.home.penalty != null &&
    tie.away.penalty != null
      ? `(${tie.home.penalty}-${tie.away.penalty} pens)`
      : null;
  return {
    matchNo,
    matchId: tie.match_id,
    round,
    state,
    a: side(tie.home, matchNo, "a", winner === "a"),
    b: side(tie.away, matchNo, "b", winner === "b"),
    liveLabel: liveLabel({ status: tie.status, minute: tie.minute, period: tie.period as any, injury_time: tie.injury_time }),
    penaltyText,
  };
}

/** Build the full 32-node tree from official data, or pure topology when null. */
export function buildTree(bracket: KnockoutBracket | null): Record<number, TieView> {
  const byNo = new Map<number, KnockoutTie>();
  for (const t of bracket?.ties ?? []) byNo.set(t.match_no, t);
  const out: Record<number, TieView> = {};
  for (const no of ALL_NOS) out[no] = viewFor(no, byNo.get(no));
  return out;
}
