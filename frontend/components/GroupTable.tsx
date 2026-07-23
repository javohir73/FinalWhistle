"use client";

import Link from "next/link";
import type { StandingRow } from "@/lib/types";
import { cn } from "@/lib/utils";
import { QualificationBar } from "./QualificationBar";
import { Flag } from "./Flag";

/** Live standings table (real results; in-play scores count provisionally),
 *  with the model's qualification bar per team. Pass `highlightTeamId` to mark
 *  one row (the followed nation on the country hub). */
export function GroupTable({
  standings,
  highlightTeamId,
  mode = "group",
}: {
  standings: StandingRow[];
  highlightTeamId?: number;
  /** "group": WC-style 4-team group — Top-2 qualification column + shading.
   *  "league": full-season table (D1) — the sim's qualification_prob still
   *  means "top two", which is not a real finish line in a 20-team league,
   *  so the column and the top-2 shading are dropped until the simulator
   *  grows league finish lines (title/UCL/relegation). */
  mode?: "group" | "league";
}) {
  const isLeague = mode === "league";
  return (
    // Auto-layout tables ignore truncate on long names ("Bosnia and
    // Herzegovina") — the scroll guard keeps 390px viewports overflow-free.
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-[11px] uppercase tracking-wider text-muted">
          <th className="pb-2 pr-2 font-medium">Team</th>
          <th className="px-1 text-center font-medium" title="Points">Pts</th>
          <th className="px-1 text-center font-medium" title="Goal difference">GD</th>
          {!isLeague && (
            <th className="pb-2 pl-2 text-right font-medium" title="Chance of finishing in the top two (direct qualification)">Top 2</th>
          )}
        </tr>
      </thead>
      <tbody>
        {standings.map((row, i) => (
          <tr
            key={row.team_id}
            className={cn(
              "border-t border-border",
              !isLeague && i < 2 && "bg-win/[0.06]",
              row.team_id === highlightTeamId && "bg-win/10",
            )}
          >
            <td className="py-2.5 pr-2">
              <Link
                href={`/team/${row.team_id}`}
                onClick={(e) => e.stopPropagation()}
                className="flex items-center gap-2 hover:text-lime-deep sm:gap-2.5"
              >
                <span className="w-4 shrink-0 text-center text-xs font-semibold text-muted">
                  {i + 1}
                </span>
                <span className="shrink-0">
                  <Flag team={row.team} size={20} />
                </span>
                <span
                  className={cn(
                    "min-w-0 font-medium leading-tight",
                    row.team_id === highlightTeamId && "font-bold",
                  )}
                >
                  {row.team}
                </span>
              </Link>
            </td>
            <td className="px-1 text-center font-semibold tabular-nums">{row.projected_points}</td>
            <td className="px-1 text-center tabular-nums text-muted">
              {row.projected_goal_diff > 0 ? `+${row.projected_goal_diff}` : row.projected_goal_diff}
            </td>
            {!isLeague && (
              <td className="py-2.5 pl-2">
                <div className="flex justify-end">
                  <QualificationBar prob={row.qualification_prob} />
                </div>
              </td>
            )}
          </tr>
        ))}
      </tbody>
      </table>
    </div>
  );
}
