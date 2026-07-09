import { ClubBadge } from "@/components/ClubBadge";
import type { LadderRow } from "@/lib/types";

/** Standings table modeled on GroupTable; top-8 (finals) rows get the lime tint. */
export function LadderTable({ rows, compact = false }: { rows: LadderRow[]; compact?: boolean }) {
  const shown = compact ? rows.slice(0, 4) : rows;
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left font-display text-[11px] uppercase tracking-wider text-muted">
          <th className="py-1.5 pr-2 font-semibold">Club</th>
          <th className="py-1.5 text-right font-semibold">P</th>
          {!compact && <th className="py-1.5 text-right font-semibold">W–L–D</th>}
          <th className="py-1.5 text-right font-semibold">Diff</th>
          <th className="py-1.5 text-right font-semibold">Pts</th>
        </tr>
      </thead>
      <tbody>
        {shown.map((r) => (
          <tr key={r.team_id}
              className={r.rank <= 8 ? "border-t border-border bg-win/[0.06]" : "border-t border-border"}>
            <td className="flex items-center gap-2 py-2 pr-2">
              <span className="w-5 text-xs tabular-nums text-muted">{r.rank}</span>
              <ClubBadge name={r.name} size={20} />
              <span className="font-medium">{r.name}</span>
            </td>
            <td className="py-2 text-right tabular-nums">{r.played}</td>
            {!compact && (
              <td className="py-2 text-right tabular-nums">{r.wins}–{r.losses}–{r.draws}</td>
            )}
            <td className="py-2 text-right tabular-nums">{r.diff > 0 ? `+${r.diff}` : r.diff}</td>
            <td className="py-2 text-right font-bold tabular-nums">{r.points}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
