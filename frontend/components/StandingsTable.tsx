"use client";

import Link from "next/link";
import type { StandingRow } from "@/lib/types";
import type { StandingsZone } from "@/lib/sports";
import { zoneForRank, zoneToneClasses } from "@/lib/standingsZones";
import { cn } from "@/lib/utils";
import { QualificationBar } from "./QualificationBar";
import { Flag } from "./Flag";

/** Solid swatch color per zone tone, for the legend dots. The rows wear the
 *  faint tints from zoneToneClasses; the legend needs the full-strength hue.
 *  Same tone->color families as zoneToneClasses (cl/promo/finals lime, europa
 *  gold, releg rose) -- kept local so lib/standingsZones.ts's tested shape is
 *  untouched. `none` never reaches the legend (every zone carries a label). */
const ZONE_SWATCH: Record<StandingsZone["tone"], string> = {
  cl: "bg-win",
  promo: "bg-win",
  finals: "bg-win",
  europa: "bg-gold",
  releg: "bg-loss",
  none: "bg-muted",
};

/** The qualification column has to fit QualificationBar's own fixed widths
 *  (bar + printed %), which grow at sm -- pin the header label and the cell to
 *  the same width so the Pts/GD columns stay aligned between the two. */
const QUAL_COL = "w-[5.5rem] sm:w-36";

/** Floodlight standings table (design/Floodlight Prototype.dc.html, Recon 3
 *  Screen 4): a flex table with a Hanken micro-label header over rows that each
 *  wear a `border-l-[3px]` zone stripe, a faint zone tint, and a big Bricolage
 *  rank numeral tinted to the zone. `zones` drives the CL/Europa/relegation
 *  bands for league comps; pass `[]` for group/knockout tables that have no
 *  finish lines (WC26), where the Top-2 QualificationBar column carries the
 *  story instead (`showQualification`). Generalises the old GroupTable so both
 *  surfaces share one styling source. The flex layout carries ARIA table roles
 *  (table/rowgroup/row/columnheader/rowheader/cell) so it still reads as a
 *  table to screen readers -- header-to-cell association and table navigation
 *  survive the move off semantic `<table>` markup. */
export function StandingsTable({
  standings,
  zones,
  highlightTeamId,
  showQualification = false,
}: {
  standings: StandingRow[];
  zones: StandingsZone[];
  highlightTeamId?: number;
  showQualification?: boolean;
}) {
  return (
    // Auto-width rows would let a long name ("Bosnia and Herzegovina") wrap; the
    // scroll guard keeps 390px viewports overflow-free either way.
    <div className="overflow-x-auto">
      <div role="table" aria-label="Standings">
        <div role="rowgroup">
          <div
            role="row"
            className="flex items-center border-b border-border border-l-[3px] border-l-transparent py-1.5 pl-1.5 text-[9.5px] font-medium uppercase tracking-[0.1em] text-muted"
          >
            <span className="w-7 shrink-0" aria-hidden />
            <span role="columnheader" className="flex-1">Team</span>
            <span role="columnheader" className="w-10 text-right">GD</span>
            <span role="columnheader" className="w-10 text-right">Pts</span>
            {showQualification && (
              <span role="columnheader" className={cn(QUAL_COL, "text-right")}>Top 2</span>
            )}
          </div>
        </div>

        <div role="rowgroup">
          {standings.map((row, i) => {
            const zone = zoneForRank(zones, i + 1);
            const { stripe, bg, rankText } = zoneToneClasses(zone?.tone ?? "none");
            const highlighted = row.team_id === highlightTeamId;
            return (
              <div
                key={row.team_id}
                role="row"
                className={cn(
                  "flex items-center border-b border-border border-l-[3px] pl-1.5",
                  stripe || "border-l-transparent",
                  highlighted ? "bg-win/10" : bg,
                )}
              >
                {/* rank + flag + name is the tap target (>=44px via py-3) and
                    the row header, so AT announces the team alongside each cell */}
                <div role="rowheader" className="min-w-0 flex-1">
                  <Link
                    href={`/team/${row.team_id}`}
                    onClick={(e) => e.stopPropagation()}
                    className="flex min-w-0 items-center gap-2.5 py-3 hover:text-lime-deep"
                  >
                    <span className={cn("text-rank w-7 shrink-0 text-center", rankText || "text-muted")}>
                      {i + 1}
                    </span>
                    <span className="shrink-0">
                      <Flag team={row.team} size={22} />
                    </span>
                    <span
                      className={cn(
                        "min-w-0 font-display font-bold leading-tight",
                        highlighted && "text-lime-deep",
                      )}
                    >
                      {row.team}
                    </span>
                  </Link>
                </div>
                <span role="cell" className="w-10 text-right text-[13px] tabular-nums text-foreground">
                  {row.projected_goal_diff > 0 ? `+${row.projected_goal_diff}` : row.projected_goal_diff}
                </span>
                <span role="cell" className="w-10 text-right font-display text-sm font-bold tabular-nums">
                  {row.projected_points}
                </span>
                {showQualification && (
                  <div role="cell" className={cn(QUAL_COL, "flex justify-end")}>
                    <QualificationBar prob={row.qualification_prob} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {zones.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-3">
          {zones.map((z) => (
            <span
              key={z.label}
              className="inline-flex items-center gap-1.5 text-[9.5px] text-muted"
            >
              <i className={cn("h-2 w-2 rounded-[2px]", ZONE_SWATCH[z.tone])} aria-hidden />
              {z.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
