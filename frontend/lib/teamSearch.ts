import type { Team } from "./types";

/** Rank nations for a search query: prefix matches first, then substring
 *  matches, ties broken alphabetically (case-insensitive). An empty/whitespace
 *  query returns every team in alphabetical order. Pure — shared by the
 *  onboarding country picker and the home dashboard team search. */
export function rankTeams(teams: Team[], query: string): Team[] {
  const q = query.trim().toLowerCase();
  const sorted = [...teams].sort((a, b) => a.name.localeCompare(b.name));
  if (!q) return sorted;
  return sorted
    .filter((t) => t.name.toLowerCase().includes(q))
    .sort((a, b) => {
      const ap = a.name.toLowerCase().startsWith(q) ? 0 : 1;
      const bp = b.name.toLowerCase().startsWith(q) ? 0 : 1;
      return ap - bp || a.name.localeCompare(b.name);
    });
}
