"use client";

import type { StandingRow } from "@/lib/types";
import { StandingsTable } from "./StandingsTable";

/** Thin wrapper over StandingsTable so the WC26 group tables and the league
 *  standings share one styling source (Floodlight P2). Keeps its original
 *  public shape (`standings`, `highlightTeamId`, `mode`) so GroupCard and the
 *  group-detail page compile unchanged. Groups have no CL/Europa/relegation
 *  finish lines, so `zones` is always [] here -- the story is the Top-2
 *  QualificationBar column (`showQualification`); league zone stripes are
 *  injected by callers that render StandingsTable directly (GroupsClient). */
export function GroupTable({
  standings,
  highlightTeamId,
  mode = "group",
}: {
  standings: StandingRow[];
  highlightTeamId?: number;
  /** "group": WC-style 4-team group — Top-2 qualification column.
   *  "league": full-season table — the sim's qualification_prob still means
   *  "top two", which is not a real finish line in a 20-team league, so the
   *  column is dropped until the simulator grows league finish lines. */
  mode?: "group" | "league";
}) {
  return (
    <StandingsTable
      standings={standings}
      zones={[]}
      highlightTeamId={highlightTeamId}
      showQualification={mode === "group"}
    />
  );
}
