/** Pure logic for the interactive "My Bracket" builder.
 *  Teams are identified by name (unique across the tournament); a separate map
 *  resolves names to ids/strength for links and tie-breaks. */
import { R32, THIRD_SLOTS, KO_TREE, FINAL_MATCH, type Slot } from "./bracketStructure";

export type Outcome = "home" | "draw" | "away";
export type GroupPicks = Record<number, Outcome>; // matchId -> outcome
export type KnockoutPicks = Record<number, string>; // match no -> winner team name

export interface BTeam {
  id: number;
  name: string;
  strength: number; // model rating proxy (e.g. qualification prob), for tie-breaks
}
export interface BFixture {
  matchId: number;
  home: string;
  away: string;
}
export interface BGroup {
  letter: string;
  teams: BTeam[];
  fixtures: BFixture[];
}

export interface TableRow {
  name: string;
  points: number;
  won: number;
  drawn: number;
  lost: number;
}

/** League table for one group from the user's match-outcome picks.
 *  Ranked by points, then by model strength (a deterministic tie-break). */
export function groupTable(group: BGroup, picks: GroupPicks): TableRow[] {
  const row: Record<string, TableRow> = {};
  for (const t of group.teams) row[t.name] = { name: t.name, points: 0, won: 0, drawn: 0, lost: 0 };

  for (const fx of group.fixtures) {
    const o = picks[fx.matchId];
    if (!o || !row[fx.home] || !row[fx.away]) continue;
    if (o === "home") {
      row[fx.home].points += 3; row[fx.home].won++; row[fx.away].lost++;
    } else if (o === "away") {
      row[fx.away].points += 3; row[fx.away].won++; row[fx.home].lost++;
    } else {
      row[fx.home].points += 1; row[fx.away].points += 1;
      row[fx.home].drawn++; row[fx.away].drawn++;
    }
  }

  const strength: Record<string, number> = {};
  for (const t of group.teams) strength[t.name] = t.strength;
  return Object.values(row).sort(
    (a, b) => b.points - a.points || (strength[b.name] ?? 0) - (strength[a.name] ?? 0),
  );
}

/** True once every group fixture has a pick (group stage complete). */
export function groupStageComplete(groups: BGroup[], picks: GroupPicks): boolean {
  return groups.every((g) => g.fixtures.every((f) => picks[f.matchId]));
}

/** Greedy, deterministic assignment of qualified thirds to their eligible slots
 *  (most-constrained slot first, with backtracking) — mirrors the backend. */
export function assignThirds(qualifyingGroups: string[]): Record<number, string> {
  const slots = [...THIRD_SLOTS].sort(
    (a, b) =>
      a.elig.filter((g) => qualifyingGroups.includes(g)).length -
      b.elig.filter((g) => qualifyingGroups.includes(g)).length,
  );
  const assignment: Record<number, string> = {};
  const used = new Set<string>();

  const backtrack = (i: number): boolean => {
    if (i === slots.length) return true;
    const { no, elig } = slots[i];
    const cands = qualifyingGroups.filter((g) => elig.includes(g) && !used.has(g)).sort();
    for (const g of cands) {
      used.add(g);
      assignment[no] = g;
      if (backtrack(i + 1)) return true;
      used.delete(g);
      delete assignment[no];
    }
    return false;
  };
  backtrack(0);
  return assignment;
}

export interface Seeding {
  /** match no -> { a, b } team names for the Round of 32 */
  r32: Record<number, { a: string; b: string }>;
}

/** Seed the official Round of 32 from completed group tables. */
export function seedKnockouts(groups: BGroup[], picks: GroupPicks): Seeding {
  const tables: Record<string, TableRow[]> = {};
  for (const g of groups) tables[g.letter] = groupTable(g, picks);

  // Best 8 third-placed teams (points, then strength).
  const strengthByName: Record<string, number> = {};
  for (const g of groups) for (const t of g.teams) strengthByName[t.name] = t.strength;
  const thirds = groups
    .map((g) => ({ group: g.letter, ...tables[g.letter][2] }))
    .filter((t) => t.name)
    .sort((a, b) => b.points - a.points || (strengthByName[b.name] ?? 0) - (strengthByName[a.name] ?? 0))
    .slice(0, 8);
  const thirdTeamByGroup: Record<string, string> = {};
  for (const t of thirds) thirdTeamByGroup[t.group] = t.name;
  const assignment = assignThirds(thirds.map((t) => t.group));

  const resolve = (slot: Slot, no: number): string => {
    if ("third" in slot) return thirdTeamByGroup[assignment[no]] ?? "";
    return tables[slot.g]?.[slot.pos - 1]?.name ?? "";
  };

  const r32: Record<number, { a: string; b: string }> = {};
  for (const tie of R32) r32[tie.no] = { a: resolve(tie.a, tie.no), b: resolve(tie.b, tie.no) };
  return { r32 };
}

/** The two sides of any knockout match given the seeding + current winner picks.
 *  Either side may be undefined if an upstream tie hasn't been decided yet. */
export function matchSides(
  no: number,
  seeding: Seeding,
  ko: KnockoutPicks,
): { a?: string; b?: string } {
  if (seeding.r32[no]) return seeding.r32[no];
  const feeders = KO_TREE[no];
  if (!feeders) return {};
  return { a: ko[feeders[0]], b: ko[feeders[1]] };
}

export function champion(ko: KnockoutPicks): string | undefined {
  return ko[FINAL_MATCH];
}

/** Drop knockout picks that are no longer valid (their team isn't in the tie
 *  anymore because an upstream pick changed). Returns a cleaned copy. */
export function pruneKnockoutPicks(seeding: Seeding, ko: KnockoutPicks): KnockoutPicks {
  // Resolve in bracket order so upstream fixes propagate before downstream checks.
  const order = [...R32.map((m) => m.no), ...Object.keys(KO_TREE).map(Number)];
  const cleaned: KnockoutPicks = { ...ko };
  for (const no of order) {
    const { a, b } = matchSides(no, seeding, cleaned);
    const pick = cleaned[no];
    if (pick && pick !== a && pick !== b) delete cleaned[no];
  }
  return cleaned;
}
