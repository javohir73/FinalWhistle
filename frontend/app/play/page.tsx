import type { Metadata } from "next";
import { getKnockoutOddsServer, getNrlTipsheetServer } from "@/lib/api";
import { getTournament } from "@/lib/tournament";
import type { TournamentOdds } from "@/lib/types";
import type { BracketChampion } from "@/components/play/PlayBracketCard";
import { PlayHub } from "./PlayHub";

// Same ISR posture as /nrl/tips and /tips -- the shell is evergreen (nothing
// user-specific here; picks and leaderboards resolve inside the client
// sections), so the round rolls week to week under one stable URL.
export const revalidate = 300;

export const metadata: Metadata = {
  title: "Play — beat the AI across every competition",
  description:
    "One place to make your picks against the model: the World Cup bracket, league score tips, and this week's NRL round — every pick graded on a public record.",
  alternates: { canonical: "/play" },
};

/** The model's predicted champion for the bracket card: the top-`win_title`
 *  team. Filters out null win_title first so a pre-simulation payload (every
 *  win_title null) yields null -- PlayBracketCard then degrades to a plain link
 *  rather than printing a "—%" champion. Mirrors AIBracket's champion pick in
 *  app/brackets/BracketsClient.tsx (sort by win_title desc), minus the topology. */
function topChampion(odds: TournamentOdds[]): BracketChampion | null {
  const top = odds
    .filter((o) => o.win_title != null)
    .sort((a, b) => (b.win_title ?? 0) - (a.win_title ?? 0))[0];
  return top ? { team: top.team, winTitle: top.win_title as number } : null;
}

/** The Floodlight Play hub (design: Floodlight Implementation Plan, P5). Merges
 *  the WC26 bracket, league tips and NRL tips into one surface grouped by sport.
 *  Server-fetches, in parallel: the current NRL round (seeds the NRL group, same
 *  call as /nrl/tips), the active tournament (gates the bracket entry on
 *  `has_brackets`, exactly as app/brackets does), and the knockout odds (surface
 *  the predicted champion on the bracket card). Each degrades honestly to
 *  null/false so the hub always renders. League tips carry no public seed (they
 *  resolve client-side, exactly as /tips does today). */
export default async function PlayPage() {
  const [nrlTipsheet, tournament, odds] = await Promise.all([
    getNrlTipsheetServer().catch(() => null),
    getTournament(),
    getKnockoutOddsServer().catch(() => null),
  ]);

  const hasBrackets = tournament.has_brackets;
  const champion = hasBrackets && odds ? topChampion(odds) : null;

  return <PlayHub nrlTipsheet={nrlTipsheet} hasBrackets={hasBrackets} champion={champion} />;
}
