"use client";

import Link from "next/link";
import type { StandingRow } from "@/lib/types";
import type { StandingsZone } from "@/lib/sports";
import { zoneForRank, zoneToneClasses } from "@/lib/standingsZones";
import { cn } from "@/lib/utils";
import { QualificationBar } from "./QualificationBar";
import { ClubBadge } from "./ClubBadge";
import { TeamBadge } from "./TeamBadge";

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

/** The optional numeric columns a caller can slot between the team cell and the
 *  qualification column. Football uses the GD/Pts default (`columns` omitted);
 *  the NRL ladder passes W-L / Diff / Pts / Top-8% (design/Floodlight
 *  Prototype.dc.html, the NRL ladder surface). */
export type StandingsColumn = "gd" | "pts" | "wl" | "diff" | "played" | "top8";

/** Header label + width for each numeric column. All right-aligned; the widths
 *  keep the header row and the body cells in the same grid. `gloss` expands a
 *  format-knowledge label for first-time fans (title tooltip + accessible
 *  name); columns whose label says it all omit it. */
const NUMERIC_HEADERS: Record<
  StandingsColumn,
  { label: string; width: string; gloss?: string }
> = {
  gd: { label: "GD", width: "w-10", gloss: "Goal difference" },
  pts: { label: "Pts", width: "w-10", gloss: "Points" },
  wl: { label: "W–L", width: "w-12", gloss: "Wins–losses" },
  diff: { label: "Diff", width: "w-10", gloss: "Points difference" },
  played: { label: "P", width: "w-10", gloss: "Games played" },
  top8: {
    label: "Top 8%",
    width: "w-14",
    gloss: "Projected chance of finishing in the top 8 and making the finals",
  },
};

/** Shared right-aligned value-cell class (matches the existing GD cell). */
const VALUE_CELL = "text-right text-[13px] tabular-nums text-foreground";

/** Row shape the table accepts: a superset of StandingRow (football) plus the
 *  NRL ladder metrics, every metric optional so a StandingRow[] stays
 *  assignable (arrays skip excess-property checks). Football callers pass
 *  StandingRow[] unchanged; the NRL ladder passes rows carrying
 *  wins/losses/diff/projected_points/projection_pct. `team_id`/`team` are the
 *  only required fields -- they drive the row key, link, crest, and name. */
export interface StandingsTableRow {
  team_id: number;
  team: string;
  // The row's real ladder/table position. Omitted by the full, pre-sorted
  // tables (football + full NRL ladder) where array index+1 already equals the
  // rank; carried explicitly when the caller passes a filtered, non-contiguous
  // subset (match-detail's two clubs) so the numeral and zone reflect the true
  // position, not the array index.
  rank?: number;
  projected_points?: number;
  projected_goals_for?: number;
  projected_goal_diff?: number;
  qualification_prob?: number | null;
  played?: number;
  wins?: number;
  draws?: number;
  losses?: number;
  points?: number;
  diff?: number;
  projection_pct?: number | null;
}

/** Signed integer the way the GD/Diff columns print it: "+5", "-3", "0"; blank
 *  when the value is missing so a partial row degrades to an empty cell rather
 *  than "NaN". Mirrors the football GD cell's existing +N / N formatting. */
function signed(n: number | undefined): string {
  if (n == null) return "";
  return n > 0 ? `+${n}` : `${n}`;
}

/** One numeric body cell for the generic `columns` path (the NRL ladder and any
 *  future caller that passes `columns`). The football default path renders its
 *  GD/Pts cells inline (see StandingsTable) to stay byte-identical. */
function renderCell(key: StandingsColumn, row: StandingsTableRow) {
  switch (key) {
    case "gd":
      return (
        <span key={key} role="cell" className={cn("w-10", VALUE_CELL)}>
          {signed(row.projected_goal_diff)}
        </span>
      );
    case "pts":
      return (
        <span key={key} role="cell" className="w-10 text-right font-display text-sm font-bold tabular-nums">
          {row.projected_points}
        </span>
      );
    case "wl":
      return (
        <span key={key} role="cell" className={cn("w-12", VALUE_CELL)}>
          {row.wins}–{row.losses}
        </span>
      );
    case "diff":
      return (
        <span key={key} role="cell" className={cn("w-10", VALUE_CELL)}>
          {signed(row.diff)}
        </span>
      );
    case "played":
      return (
        <span key={key} role="cell" className={cn("w-10", VALUE_CELL)}>
          {row.played}
        </span>
      );
    case "top8": {
      // projColor from the prototype, simplified to the closed lime/muted pair:
      // a live top-8 chance (>=50%) reads lime, everything else (incl. the "—"
      // placeholder) reads muted. The printed % carries the signal, not colour.
      const p = row.projection_pct;
      return (
        <span
          key={key}
          role="cell"
          className={cn(
            "w-14 text-right text-[13px] tabular-nums",
            p != null && p >= 0.5 ? "text-lime-deep" : "text-muted",
          )}
        >
          {p != null ? `${Math.round(p * 100)}%` : "—"}
        </span>
      );
    }
  }
}

/** The football GD + Pts body cells, rendered byte-for-byte as the pre-NRL
 *  component did. The default (no `columns`) path is the football surface, so
 *  the one documented narrowing to StandingRow is safe -- projected_* are
 *  required there. */
function footballNumericCells(row: StandingsTableRow) {
  const s = row as StandingRow;
  return (
    <>
      <span role="cell" className="w-10 text-right text-[13px] tabular-nums text-foreground">
        {s.projected_goal_diff > 0 ? `+${s.projected_goal_diff}` : s.projected_goal_diff}
      </span>
      <span role="cell" className="w-10 text-right font-display text-sm font-bold tabular-nums">
        {s.projected_points}
      </span>
    </>
  );
}

/** Floodlight standings table (design/Floodlight Prototype.dc.html, Recon 3
 *  Screen 4): a flex table with a Hanken micro-label header over rows that each
 *  wear a `border-l-[3px]` zone stripe, a faint zone tint, and a big Bricolage
 *  rank numeral tinted to the zone. `zones` drives the CL/Europa/relegation
 *  bands for league comps; pass `[]` for group/knockout tables that have no
 *  finish lines (WC26), where the Top-2 QualificationBar column carries the
 *  story instead (`showQualification`). Generalises the old GroupTable so both
 *  surfaces share one styling source; `badge`/`teamBasePath`/`teamHeader`/
 *  `columns` additionally paint the NRL ladder (club crests, /nrl/team links,
 *  W-L / Diff / Pts / Top-8% columns) off the same component. The flex layout
 *  carries ARIA table roles (table/rowgroup/row/columnheader/rowheader/cell) so
 *  it still reads as a table to screen readers -- header-to-cell association
 *  and table navigation survive the move off semantic `<table>` markup. */
export function StandingsTable({
  standings,
  zones,
  highlightTeamId,
  showQualification = false,
  badge = "flag",
  teamBasePath = "/team",
  teamHeader = "Team",
  columns,
}: {
  standings: StandingsTableRow[];
  zones: StandingsZone[];
  highlightTeamId?: number;
  showQualification?: boolean;
  badge?: "flag" | "club";
  teamBasePath?: string;
  teamHeader?: string;
  columns?: StandingsColumn[];
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
            <span role="columnheader" className="flex-1">{teamHeader}</span>
            {columns ? (
              columns.map((key) => (
                <span
                  key={key}
                  role="columnheader"
                  title={NUMERIC_HEADERS[key].gloss}
                  aria-label={NUMERIC_HEADERS[key].gloss}
                  className={cn(NUMERIC_HEADERS[key].width, "text-right")}
                >
                  {NUMERIC_HEADERS[key].label}
                </span>
              ))
            ) : (
              <>
                <span role="columnheader" title="Goal difference" aria-label="Goal difference" className="w-10 text-right">GD</span>
                <span role="columnheader" title="Points" aria-label="Points" className="w-10 text-right">Pts</span>
              </>
            )}
            {showQualification && (
              <span
                role="columnheader"
                title="Chance of finishing in the top two and qualifying"
                aria-label="Chance of finishing in the top two and qualifying"
                className={cn(QUAL_COL, "text-right")}
              >
                Top 2
              </span>
            )}
          </div>
        </div>

        <div role="rowgroup">
          {standings.map((row, i) => {
            // Real rank when the row carries it (a filtered subset), else the
            // array position — index+1 === rank for the full, pre-sorted tables.
            const rank = row.rank ?? i + 1;
            const zone = zoneForRank(zones, rank);
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
                {/* rank + crest + name is the tap target (>=44px via py-3) and
                    the row header, so AT announces the team alongside each cell */}
                <div role="rowheader" className="min-w-0 flex-1">
                  <Link
                    href={`${teamBasePath}/${row.team_id}`}
                    onClick={(e) => e.stopPropagation()}
                    className="flex min-w-0 items-center gap-2.5 py-3 hover:text-lime-deep"
                  >
                    <span className={cn("text-rank w-7 shrink-0 text-center", rankText || "text-muted")}>
                      {rank}
                    </span>
                    <span className="shrink-0">
                      {badge === "club" ? (
                        <ClubBadge
                          name={row.team}
                          size={30}
                          className="rounded-lg border border-border/70 bg-surface-2/70"
                        />
                      ) : (
                        <TeamBadge team={row.team} size={22} />
                      )}
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
                {columns
                  ? columns.map((key) => renderCell(key, row))
                  : footballNumericCells(row)}
                {showQualification && (
                  <div role="cell" className={cn(QUAL_COL, "flex justify-end")}>
                    <QualificationBar prob={row.qualification_prob ?? null} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Zone legend only makes sense above rows it can point at — an empty
          table with an orphan legend reads as broken, not pre-draw. */}
      {zones.length > 0 && standings.length > 0 && (
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
