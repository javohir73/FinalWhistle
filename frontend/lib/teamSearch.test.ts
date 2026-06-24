/** rankTeams: prefix matches before substring matches, ties alphabetical;
 *  an empty query returns every team in alphabetical order. */
import { rankTeams } from "./teamSearch";
import type { Team } from "./types";

const team = (id: number, name: string): Team => ({
  id,
  name,
  country_code: null,
  confederation: null,
  fifa_rank: null,
  elo_rating: null,
  is_host: false,
});

const teams: Team[] = [
  team(1, "Qatar"),
  team(2, "Argentina"),
  team(3, "Brazil"),
  team(4, "Spain"),
];

it("returns every team alphabetically when the query is empty or whitespace", () => {
  expect(rankTeams(teams, "").map((t) => t.name)).toEqual([
    "Argentina", "Brazil", "Qatar", "Spain",
  ]);
  expect(rankTeams(teams, "   ").map((t) => t.name)).toEqual([
    "Argentina", "Brazil", "Qatar", "Spain",
  ]);
});

it("ranks prefix matches ahead of substring matches", () => {
  // "ar" is a prefix of Argentina and a substring of Qatar (qatAR).
  expect(rankTeams(teams, "ar").map((t) => t.name)).toEqual(["Argentina", "Qatar"]);
});

it("is case-insensitive", () => {
  expect(rankTeams(teams, "ARG").map((t) => t.name)).toEqual(["Argentina"]);
});

it("returns an empty array when nothing matches", () => {
  expect(rankTeams(teams, "zzz")).toEqual([]);
});

it("breaks ties alphabetically among prefix matches", () => {
  const ss = [team(5, "Senegal"), team(6, "Serbia"), team(7, "Spain")];
  expect(rankTeams(ss, "se").map((t) => t.name)).toEqual(["Senegal", "Serbia"]);
});
