/** Official 2026 World Cup knockout structure (mirrors ml/simulate/bracket.py).
 *  Used by the interactive "My Bracket" builder to seed and advance the bracket. */

export type Placement = { g: string; pos: 1 | 2 };
export type Slot = Placement | { third: true };

/** Round of 32 pairings (match number, side A, side B). */
export const R32: { no: number; a: Slot; b: Slot }[] = [
  { no: 73, a: { g: "A", pos: 2 }, b: { g: "B", pos: 2 } },
  { no: 74, a: { g: "E", pos: 1 }, b: { third: true } },
  { no: 75, a: { g: "F", pos: 1 }, b: { g: "C", pos: 2 } },
  { no: 76, a: { g: "C", pos: 1 }, b: { g: "F", pos: 2 } },
  { no: 77, a: { g: "I", pos: 1 }, b: { third: true } },
  { no: 78, a: { g: "E", pos: 2 }, b: { g: "I", pos: 2 } },
  { no: 79, a: { g: "A", pos: 1 }, b: { third: true } },
  { no: 80, a: { g: "L", pos: 1 }, b: { third: true } },
  { no: 81, a: { g: "D", pos: 1 }, b: { third: true } },
  { no: 82, a: { g: "G", pos: 1 }, b: { third: true } },
  { no: 83, a: { g: "K", pos: 2 }, b: { g: "L", pos: 2 } },
  { no: 84, a: { g: "H", pos: 1 }, b: { g: "J", pos: 2 } },
  { no: 85, a: { g: "B", pos: 1 }, b: { third: true } },
  { no: 86, a: { g: "J", pos: 1 }, b: { g: "H", pos: 2 } },
  { no: 87, a: { g: "K", pos: 1 }, b: { third: true } },
  { no: 88, a: { g: "D", pos: 2 }, b: { g: "G", pos: 2 } },
];

/** Third-place slots: match number → groups whose 3rd may fill it. */
export const THIRD_SLOTS: { no: number; elig: string[] }[] = [
  { no: 74, elig: ["A", "B", "C", "D", "F"] },
  { no: 77, elig: ["C", "D", "F", "G", "H"] },
  { no: 79, elig: ["C", "E", "F", "H", "I"] },
  { no: 80, elig: ["E", "H", "I", "J", "K"] },
  { no: 81, elig: ["B", "E", "F", "I", "J"] },
  { no: 82, elig: ["A", "E", "H", "I", "J"] },
  { no: 85, elig: ["E", "F", "G", "I", "J"] },
  { no: 87, elig: ["D", "E", "I", "J", "L"] },
];

/** Bracket tree: match → the two feeder matches whose winners meet. */
export const KO_TREE: Record<number, [number, number]> = {
  // Round of 16
  89: [74, 77], 90: [73, 75], 91: [76, 78], 92: [79, 80],
  93: [83, 84], 94: [81, 82], 95: [86, 88], 96: [85, 87],
  // Quarter-finals
  97: [89, 90], 98: [93, 94], 99: [91, 92], 100: [95, 96],
  // Semi-finals
  101: [97, 98], 102: [99, 100],
  // Final
  104: [101, 102],
};

export const ROUNDS: { key: string; label: string; matches: number[] }[] = [
  { key: "r32", label: "Round of 32", matches: R32.map((m) => m.no) },
  { key: "r16", label: "Round of 16", matches: [89, 90, 91, 92, 93, 94, 95, 96] },
  { key: "qf", label: "Quarter-finals", matches: [97, 98, 99, 100] },
  { key: "sf", label: "Semi-finals", matches: [101, 102] },
  { key: "final", label: "Final", matches: [104] },
];

export const FINAL_MATCH = 104;

/** 3rd-place match (103): NOT in KO_TREE — it is fed by the two SF LOSERS
 *  (101, 102), not winners. Rendered as a detached node beside the Final. */
export const THIRD_PLACE = { no: 103, loserFeeders: [101, 102] as [number, number] };
