import Link from "next/link";
import { ClubBadge } from "@/components/ClubBadge";
import type { LadderRow } from "@/lib/types";

/** Standings table modeled on GroupTable; top-8 (finals) rows get the lime tint.
 *  Each club cell links through to its profile page. `projections` (Wave 1
 *  finals Monte Carlo, keyed by team name) adds Top 8%/Top 4% columns --
 *  hidden entirely when omitted or empty. */
export function LadderTable({
  rows,
  compact = false,
  projections,
}: {
  rows: LadderRow[];
  compact?: boolean;
  projections?: Record<string, { top8: number; top4: number }>;
}) {
  const shown = compact ? rows.slice(0, 4) : rows;
  const showProjections = !compact && !!projections && Object.keys(projections).length > 0;

  return (
    // Mirrors GroupTable's scroll guard: auto-layout tables ignore truncate on
    // long club names, so overflow-x-auto keeps narrow viewports overflow-free.
    <div className="overflow-x-auto">
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left font-display text-[11px] uppercase tracking-wider text-muted">
          <th className="py-1.5 pr-2 font-semibold">Club</th>
          <th className="py-1.5 text-right font-semibold">P</th>
          {!compact && <th className="py-1.5 text-right font-semibold">W–L–D</th>}
          <th className="py-1.5 text-right font-semibold">Diff</th>
          <th className="py-1.5 text-right font-semibold">Pts</th>
          {showProjections && (
            <>
              <th className="py-1.5 text-right font-semibold">Top 8%</th>
              <th className="py-1.5 text-right font-semibold">Top 4%</th>
            </>
          )}
        </tr>
      </thead>
      <tbody>
        {shown.map((r) => {
          const proj = projections?.[r.name];
          return (
            <tr key={r.team_id}
                className={r.rank <= 8 ? "border-t border-border bg-win/[0.06]" : "border-t border-border"}>
              <td className="flex items-center gap-2 py-2 pr-2">
                <span className="w-5 text-xs tabular-nums text-muted">{r.rank}</span>
                <Link
                  href={`/nrl/team/${r.team_id}`}
                  className="flex min-w-0 items-center gap-2 underline-offset-2 hover:underline"
                >
                  <ClubBadge name={r.name} size={20} />
                  <span className="font-medium">{r.name}</span>
                </Link>
              </td>
              <td className="py-2 text-right tabular-nums">{r.played}</td>
              {!compact && (
                <td className="py-2 text-right tabular-nums">{r.wins}–{r.losses}–{r.draws}</td>
              )}
              <td className="py-2 text-right tabular-nums">{r.diff > 0 ? `+${r.diff}` : r.diff}</td>
              <td className="py-2 text-right font-bold tabular-nums">{r.points}</td>
              {showProjections && (
                <>
                  <td className="py-2 text-right tabular-nums text-muted">
                    {proj ? `${Math.round(proj.top8 * 100)}%` : "—"}
                  </td>
                  <td className="py-2 text-right tabular-nums text-muted">
                    {proj ? `${Math.round(proj.top4 * 100)}%` : "—"}
                  </td>
                </>
              )}
            </tr>
          );
        })}
      </tbody>
    </table>
    </div>
  );
}
