import Link from "next/link";
import type { StandingRow } from "@/lib/types";
import { cn } from "@/lib/utils";
import { QualificationBar } from "./QualificationBar";
import { Flag } from "./Flag";

/** Predicted standings table with a qualification bar per team. */
export function GroupTable({ standings }: { standings: StandingRow[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-[11px] uppercase tracking-wider text-muted">
          <th className="pb-2 pr-2 font-medium">Team</th>
          <th className="px-1 text-center font-medium" title="Predicted points">Pts</th>
          <th className="px-1 text-center font-medium" title="Predicted goal difference">GD</th>
          <th className="pb-2 pl-2 text-right font-medium">Qualify</th>
        </tr>
      </thead>
      <tbody>
        {standings.map((row, i) => (
          <tr
            key={row.team_id}
            className={cn(
              "border-t border-border/50",
              i < 2 && "bg-win/[0.04]",
            )}
          >
            <td className="py-2.5 pr-2">
              <Link
                href={`/team/${row.team_id}`}
                className="flex items-center gap-2.5 hover:text-win"
              >
                <span className="w-4 text-center text-xs font-semibold text-muted">
                  {i + 1}
                </span>
                <Flag team={row.team} size={20} />
                <span className="font-medium">{row.team}</span>
              </Link>
            </td>
            <td className="px-1 text-center font-semibold tabular-nums">{row.points}</td>
            <td className="px-1 text-center tabular-nums text-muted">
              {row.goal_diff > 0 ? `+${row.goal_diff}` : row.goal_diff}
            </td>
            <td className="py-2.5 pl-2">
              <div className="flex justify-end">
                <QualificationBar prob={row.qualification_prob} />
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
